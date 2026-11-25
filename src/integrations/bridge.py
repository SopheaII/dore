"""Line-based bridge for editor plugins (opencode, etc.) that want dore without MCP.

    dore-bridge

Reads one JSON request per line from stdin, writes one JSON response per line to stdout.
The embedder and store are loaded once and kept warm, so per-message hooks cost milliseconds
instead of the ~1.5 s of starting a new process every time.

Requests: {"id": any, "op": "...", ...}
  brief   project                 -> short session-start summary (SQLite only)
  prompt  prompt, project, session_id -> notes worth adding before this prompt ("" if none)
  learn   messages, project       -> save the user's own statements from these messages
  recall  query, project, k       -> formatted search hits (or "#<id>" for one full note)
  remember facts, project, user_said -> save facts, return their ids
  correct correction, wrong_ids, project, user_said
  close

Every response is {"id": ..., "ok": true, "result": ...} or {"id": ..., "ok": false, "error": "..."}.
"""

from __future__ import annotations

import json
import sys

from dore.learn.statements import ORG, PERSONAL
from dore.config import Config
from dore.integrations.hooks import _State, learn_message, message_key, on_prompt
from dore.integrations.server import LONG_TEXT, correct_reply, format_hit, session_brief


class Bridge:
    def __init__(self, cfg: Config | None = None):
        self.cfg = cfg or Config()
        self._store = None
        self._learned: set[str] = set()  # message_key of prompts already learned from

    def store(self):
        if self._store is None:
            from dore.memory.embed import FastEmbedder
            from dore.memory import MemoryStore

            embedder = FastEmbedder(self.cfg.embed_model, cache_dir=str(self.cfg.cache_dir / "fastembed"))
            self._store = MemoryStore(self.cfg.db_path, self.cfg.index_path, embedder,
                                      self.cfg.duplicate_threshold, self.cfg.index_save_interval)
        return self._store

    def scope(self, project: str, text: str = "") -> str:
        """Explicit project wins; otherwise facts about the user or organisation are general."""
        if project:
            return project
        return "" if text and (PERSONAL.search(text) or ORG.search(text)) else project

    def brief(self, req: dict) -> str:
        return session_brief(self.cfg.db_path, str(req.get("project") or ""))

    def prompt(self, req: dict) -> str:
        state = _State(self.cfg.data_dir, str(req.get("session_id") or ""))
        text = on_prompt(self.store(), str(req.get("prompt") or ""), str(req.get("project") or ""), state)
        self._learned.update(state.d.get("learned", []))
        state.save()
        return text

    def learn(self, req: dict) -> list[int]:
        project = str(req.get("project") or "")
        # Messages the prompt op already learned from are skipped (no double counting).
        msgs = [str(m) for m in req.get("messages") or [] if message_key(str(m)) not in self._learned]
        if not msgs:
            return []
        store = self.store()
        ids = [i for m in msgs for i in learn_message(store, m, project)]  # same rules as Claude Code
        store.save(force=True)
        return ids

    def recall(self, req: dict) -> str:
        q = str(req.get("query") or "").strip()
        store = self.store()
        if q.startswith("#") and q[1:].isdigit():
            try:
                m = store.get(int(q[1:]))
            except KeyError:
                return "no such memory"
            return format_hit(m).split("] ", 1)[0] + "] " + m.content
        project = self.scope(str(req.get("project") or "")) or None
        k = max(1, min(int(req.get("k") or 3), 10))
        hits = store.search(q, k=k, min_similarity=0.5, project=project)
        return "\n".join(format_hit(m) for m in hits) if hits else "nothing relevant in memory"

    def remember(self, req: dict) -> str:
        from dore.memory.ingest import ingest_text

        project = str(req.get("project") or "")
        user_said = bool(req.get("user_said"))
        trust, source = ("verified", "user") if user_said else ("unverified", "agent")
        store = self.store()
        ids: list[int] = []
        for fact in (str(f).strip() for f in req.get("facts") or []):
            if not fact:
                continue
            where = self.scope(project, fact)
            if len(fact) > LONG_TEXT:
                ids += ingest_text(store, fact, source=f"{source}-text", trust="unverified", project=where)
            else:
                ids.append(store.add(fact, kind="fact", source=source, trust=trust, project=where, supersede=True))
        store.save()
        return "saved " + " ".join(f"#{i}" for i in ids) if ids else "nothing to save"

    def correct(self, req: dict) -> str:
        project = self.scope(str(req.get("project") or ""), str(req.get("correction") or ""))
        user_said = bool(req.get("user_said"))
        store = self.store()
        done, refused = store.demote(list(req.get("wrong_ids") or []), by_user=user_said)
        mid = store.add(str(req.get("correction") or ""), kind="correction",
                        source="user" if user_said else "agent",
                        trust="verified" if user_said else "unverified", project=project)
        store.save()
        return correct_reply(done, refused, mid)

    def handle(self, req: dict):
        op = req.get("op")
        if op == "brief":
            return self.brief(req)
        if op == "prompt":
            return self.prompt(req)
        if op == "learn":
            return self.learn(req)
        if op == "recall":
            return self.recall(req)
        if op == "remember":
            return self.remember(req)
        if op == "correct":
            return self.correct(req)
        if op == "close":
            return "bye"
        raise ValueError(f"unknown op {op!r}")

    def close(self):
        if self._store is not None:
            self._store.close()
            self._store = None


def main(argv: list[str] | None = None):
    bridge = Bridge()
    try:
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            rid = None
            try:
                req = json.loads(line)
                rid = req.get("id")
                result = bridge.handle(req)
                out = {"id": rid, "ok": True, "result": result}
            except Exception as exc:  # keep the bridge alive: one bad request must not kill it
                out = {"id": rid, "ok": False, "error": f"{type(exc).__name__}: {exc}"}
            print(json.dumps(out, ensure_ascii=False), flush=True)
            if isinstance(out.get("result"), str) and out.get("result") == "bye":
                break
    finally:
        bridge.close()


if __name__ == "__main__":
    main()
