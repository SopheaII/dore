"""Run Claude Code on a local model served by Ollama (>= 0.14, Anthropic-compatible API).

    dore-claude --list                          # local models Ollama has
    dore-claude qwen2.5-coder                   # start Claude Code on that model
    dore-claude qwen2.5-coder --ctx 32768 -p "…" # same, with a bigger context window
                                                 # (extra args are passed to `claude`)

Claude Code's own instructions and tool list are ~20k tokens (measured), so models
need a large context window; Ollama's default is 4096. `--ctx N` creates a copy of
the model named `<model>-ctx<N>` with that window (no new download).
Expect it to be much slower and weaker than Claude: see reports/claude-local.md.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import urllib.request

OLLAMA = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
if not OLLAMA.startswith("http"):
    OLLAMA = "http://" + OLLAMA


def _api(path: str, body: dict | None = None, timeout: float = 600):
    req = urllib.request.Request(OLLAMA + path, data=json.dumps(body).encode() if body else None,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read().decode()
    lines = [json.loads(x) for x in raw.splitlines() if x.strip()]
    return lines[-1] if lines else {}


def list_models() -> list[str]:
    return [m["name"].removesuffix(":latest") for m in _api("/api/tags").get("models", [])]


def ensure_ctx(model: str, ctx: int) -> str:
    """A copy of `model` with a context window of `ctx` tokens (created once)."""
    name = f"{model.split(':')[0]}-ctx{ctx}"
    if name not in list_models():
        res = _api("/api/create", {"model": name, "from": model, "parameters": {"num_ctx": ctx}})
        if res.get("status") != "success":
            sys.exit(f"could not create {name}: {res}")
    return name


def main(argv: list[str] | None = None):
    p = argparse.ArgumentParser(prog="dore-claude", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("model", nargs="?", help="Ollama model name (see --list)")
    p.add_argument("--list", action="store_true", help="list local models and exit")
    p.add_argument("--ctx", type=int, help="context window in tokens (e.g. 32768)")
    args, claude_args = p.parse_known_args(argv)

    try:
        models = list_models()
    except OSError as e:
        sys.exit(f"Ollama is not reachable at {OLLAMA} ({e}). Start it with: ollama serve")
    if args.list or not args.model:
        print("local models:", ", ".join(models) or "(none: ollama pull <model>)")
        return
    if args.model.removesuffix(":latest") not in models:
        sys.exit(f"unknown model {args.model!r}; local models: {', '.join(models)}")
    model = ensure_ctx(args.model, args.ctx) if args.ctx else args.model
    claude = shutil.which("claude") or sys.exit("claude (Claude Code) is not installed")
    env = dict(os.environ, ANTHROPIC_BASE_URL=OLLAMA, ANTHROPIC_AUTH_TOKEN="ollama")
    env.pop("ANTHROPIC_API_KEY", None)  # would take priority over the local endpoint
    print(f"Claude Code -> local model {model} via {OLLAMA}", file=sys.stderr)
    os.execve(claude, [claude, "--model", model, *claude_args], env)


if __name__ == "__main__":
    main()
