"""Interactive chat. Every interaction teaches the memory something.

Commands:
  /teach <fact>        save a verified fact          /protect <id>   never auto-archive it
  /correct <text>      correct the last answer       /good  /bad     rate the last answer
  /load <file>         load a text/markdown file     /mem <query>    show matching memories
  /code <task>         solve with the code checker   /stats          memory statistics
  /tests               (after /code) paste tests, end with a line containing only END
  /quit
"""

from __future__ import annotations

import argparse
import sys
import time

from .config import Config


def build_agent(cfg: Config):
    from .agent import Agent
    from .core import Core
    from .embed import FastEmbedder
    from .memory import MemoryStore

    print("Loading embedder and memory...", file=sys.stderr)
    embedder = FastEmbedder(cfg.embed_model, cache_dir=str(cfg.cache_dir / "fastembed"))
    store = MemoryStore(cfg.db_path, cfg.index_path, embedder, cfg.duplicate_threshold, cfg.index_save_interval)
    print(f"Loading core model {cfg.model_path.name}...", file=sys.stderr)
    core = Core(cfg.model_path, cfg.lora_path, n_ctx=cfg.n_ctx, n_threads=cfg.n_threads)
    return Agent(core=core, memory=store, top_k=cfg.top_k, min_similarity=cfg.min_similarity,
                 max_fix_rounds=cfg.max_fix_rounds, code_timeout_s=cfg.code_timeout_s, n_ctx=cfg.n_ctx,
                 max_auto_statements=cfg.max_auto_statements)


def read_block(prompt: str) -> str:
    print(prompt)
    lines = []
    for line in sys.stdin:
        if line.strip() == "END":
            break
        lines.append(line.rstrip("\n"))
    return "\n".join(lines)


def handle(agent, cmd: str, rest: str, line: str):
    if cmd == "/teach" and rest:
        print(f"saved verified memory #{agent.teach(rest)}")
    elif cmd == "/correct" and rest:
        print(f"saved correction #{agent.correct(rest)}; last answer marked wrong")
        if agent.last_demoted_ids:
            print(f"also marked wrong (kept, not deleted): {agent.last_demoted_ids}")
    elif cmd == "/good":
        agent.good()
        print("thanks, noted")
    elif cmd == "/bad":
        agent.bad()
        print("noted; use /correct <text> to teach the right answer")
    elif cmd == "/protect" and rest.isdigit():
        agent.memory.protect(int(rest))  # KeyError if no such memory
        print(f"memory #{rest} protected")
    elif cmd == "/load" and rest:
        from .ingest import ingest_file
        t = time.perf_counter()
        ids = ingest_file(agent.memory, rest)
        print(f"loaded {len(ids)} chunks in {time.perf_counter() - t:.1f}s (unverified)")
    elif cmd == "/mem" and rest:
        for m in agent.memory.search(rest or "", k=10, touch=False):
            print(f"#{m.id} [{m.trust}{', protected' if m.protected else ''}] "
                  f"sim={m.similarity:.2f}  {m.content[:120]!r}")
    elif cmd == "/stats":
        print(agent.memory.stats())
    elif cmd == "/code" and rest:
        tests = None
        if input("add tests? [y/N] ").strip().lower() == "y":
            tests = read_block("paste assert-based tests, finish with END:")
        t = time.perf_counter()
        r = agent.solve_code(rest, tests)
        print(f"```python\n{r.code}\n```")
        status = "PASSED" if r.check.passed else "FAILED"
        kind = "tests" if r.check.tested else "run-only (no tests: stays unverified)"
        print(f"{status} after {r.attempts} attempt(s), {kind}, {time.perf_counter() - t:.0f}s")
        if r.check.output.strip():
            print(r.check.output.strip()[-800:])
        if r.memory_id:
            print(f"saved lesson #{r.memory_id}")
    elif cmd.startswith("/"):
        print(__doc__)
    else:
        t = time.perf_counter()
        print("dore> " + agent.ask(line))
        print(f"({time.perf_counter() - t:.1f}s)", file=sys.stderr)


def main(argv: list[str] | None = None):
    p = argparse.ArgumentParser(prog="dore")
    p.add_argument("--model", help="path to a GGUF model")
    p.add_argument("--lora", help="path to a GGUF LoRA adapter")
    p.add_argument("--threads", type=int)
    args = p.parse_args(argv)

    cfg = Config()
    if args.model:
        from pathlib import Path
        cfg.model_path = Path(args.model)
    if args.lora:
        from pathlib import Path
        cfg.lora_path = Path(args.lora)
    if args.threads:
        cfg.n_threads = args.threads

    agent = build_agent(cfg)
    print(__doc__)
    try:
        while True:
            try:
                line = input("\nyou> ").strip()
            except EOFError:
                break
            if not line:
                continue
            cmd, _, rest = line.partition(" ")
            rest = rest.strip()
            if cmd == "/quit":
                break
            try:
                handle(agent, cmd, rest, line)
            except Exception as e:  # noqa: BLE001  keep the chat alive on any error
                print(f"error: {type(e).__name__}: {e}")
    finally:
        agent.memory.close()


if __name__ == "__main__":
    main()
