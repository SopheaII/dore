"""The agent: answers using memory, and learns from every interaction.

Learning paths (all instant, no training):
- ask()          -> each statement the user makes is stored ("told by the user");
                    a long paste is stored as `unverified` document chunks instead;
                    the model's answer is kept `unverified` and NOT reused until approved
- solve_code()   -> thinking loop with a checker; tested+passed -> `verified`
- teach()        -> user fact, `verified`
- correct()      -> user correction `verified`; last answer marked `wrong`
- good()/bad()   -> good() verifies the last answer (now reusable); both rate the memories used
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .checkers import CheckResult, extract_code, run_python
from .core import ChatModel
from .ingest import ingest_text
from .memory import Memory, MemoryStore

SYSTEM = (
    "You are dore, a helpful local assistant with a memory. "
    "Use the memory notes when they are relevant; otherwise answer from your own knowledge. "
    "Notes told by the user are about the user: 'I'/'my' in them means the user, so call it 'your' in answers. "
    "Verified notes are reliable. Unverified notes are usually right, so use them, but if they conflict "
    "with a verified note, trust the verified one; prefer newer notes over older ones. "
    "Only use notes that answer the question. Be concise and don't mention the notes unless asked."
)

# Added after a question about the user (the 1B model follows instructions there, not in the
# system prompt). Measured 2026-11-24 (1B, 7 questions x 8 seeds, strict check): 54/56 correct
# vs 42/56 without it; without it the model invents details ("Your dog is called Kavi").
# Longer wordings did worse: "general knowledge: answer normally" turned "Calmette Hospital"
# into "Pasteur Institute", and "copy names exactly" made it reuse the cat's name for the dog.
NO_GUESS = "(If no note above answers this, say you don't know.)"
PERSONAL = re.compile(r"\b(my|me|mine|i|i'm|am i|do i)\b", re.I)

CODE_SYSTEM = (
    "You write correct, self-contained Python 3. Reply with one ```python code block and nothing else. "
    "Use only the standard library. Do not read input() or write files."
)


QUESTION_START = re.compile(
    r"^(what|who|whom|whose|where|when|why|how|which|is|are|am|do|does|did|can|could|will|would|should|"
    r"tell me|please|explain|write|show|give|list)\b", re.I)
# "Please remember that X" / "Can you note: X" / "FYI X" -> X is a statement to store.
MEMORY_LEAD_IN = re.compile(
    r"^(?:(?:can|could|would|will) you\s+)?(?:please\s+)?(?:remember|note|keep in mind|don'?t forget|"
    r"do not forget|save)(?:\s+that)?\s*[:,]?\s+|^(?:fyi|just so you know|for your information|btw|by the way)"
    r"\s*[:,]?\s+", re.I)
# Small talk is not a fact about the user.
SMALL_TALK = re.compile(
    r"^(hi|hello|hey|thanks|thank you|thx|ok|okay|sorry|bye|goodbye|good (morning|afternoon|evening|night))\b", re.I)
# Requests: an imperative verb followed by its object ("Summarize the text", "Help me ..."),
# so nouns like "Help desk number is 555" still count as statements.
REQUEST = re.compile(
    r"^(summari[sz]e|translate|help|make|create|fix|find|check|calculate|compute|generate|draft|describe|"
    r"compare|rewrite|continue|try|run|open|read|search|look|send|remind|let'?s)\s+"
    r"(me|us|the|this|that|these|those|a|an|my|our|it|following|up|out|at|for)\b", re.I)

SOURCE_LABELS = {"user": "told by the user", "checker": "tested", "model": "earlier answer",
                 "chat-paste": "pasted by the user"}

SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+|\n+")


def split_statements(text: str) -> list[str]:
    """Sentences of `text` that state something (not questions, at least 3 words)."""
    out = []
    for sent in SENTENCE_SPLIT.split(text.strip()):
        sent = sent.strip()
        lead = MEMORY_LEAD_IN.match(sent)
        if lead:  # an explicit "remember that ...": keep the statement, even in question form
            sent = sent[lead.end():].rstrip("?").strip()
            sent = sent[:1].upper() + sent[1:]
        elif sent.endswith("?") or QUESTION_START.match(sent) or SMALL_TALK.match(sent) or REQUEST.match(sent):
            continue
        if len(sent.split()) >= 3:
            out.append(sent)
    return out


def format_memories(mems: list[Memory]) -> str:
    if not mems:
        return "Memory notes: (none relevant)"
    lines = []
    for m in mems:
        origin = SOURCE_LABELS.get(m.source, "from a document" if m.source.startswith("file:") else m.source)
        lines.append(f"- [{m.trust}, {origin}] {m.content}")
    return "Memory notes:\n" + "\n".join(lines)


@dataclass
class CodeResult:
    code: str
    check: CheckResult
    attempts: int
    memory_id: int | None


@dataclass
class Agent:
    core: ChatModel
    memory: MemoryStore
    top_k: int = 5
    min_similarity: float = 0.5  # bge-small: personal Q→statement can score ~0.51; unrelated mostly <0.5
    max_fix_rounds: int = 3
    code_timeout_s: float = 10.0
    last_answer_id: int | None = None
    last_used_ids: list[int] = field(default_factory=list)
    history: list[dict] = field(default_factory=list)
    max_history_turns: int = 4
    n_ctx: int = 4096              # model context; prompts are trimmed to fit
    max_auto_statements: int = 20  # longer messages are stored as a document, not as facts
    max_auto_chars: int = 3000
    # A used note this similar to a /correct text is taken to be the wrong fact. Measured
    # (bge-small): "My car is a Toyota" vs "My car is a Honda" 0.84; unrelated facts <= 0.62.
    conflict_similarity: float = 0.7
    last_demoted_ids: list[int] = field(default_factory=list)

    # ---------- prompt size ----------
    def _tokens(self, text: str) -> int:
        count = getattr(self.core, "count_tokens", None)
        return count(text) if count else len(text) // 3 + 1

    def _shrink(self, text: str, max_tokens: int) -> str:
        """Cut the middle out of `text` so it fits in max_tokens (head and tail are kept)."""
        n = self._tokens(text)
        if n <= max_tokens:
            return text
        keep = int(len(text) * max_tokens / n * 0.9)
        out = text
        for _ in range(6):
            head, tail = text[: keep * 2 // 3], text[len(text) - keep // 3:]
            out = f"{head}\n[... {len(text) - len(head) - len(tail)} characters cut to fit ...]\n{tail}"
            if self._tokens(out) <= max_tokens:
                break
            keep = int(keep * 0.8)
        return out

    def _build_prompt(self, system: str, history: list[dict], notes: str, body: str,
                      max_tokens: int) -> list[dict]:
        """System + as much recent history as fits + (notes, body). The body is shortened
        only if it can't fit even without history, so the model never overflows its context."""
        budget = self.n_ctx - max_tokens - 64  # 64: chat-template overhead
        # Notes may use at most half the budget: drop the lowest-ranked ones first.
        lines = notes.split("\n")
        while len(lines) > 2 and self._tokens("\n".join(lines)) > budget // 2:
            lines.pop()
        notes = self._shrink("\n".join(lines), budget // 2) if notes else notes
        fixed = self._tokens(system) + self._tokens(notes) + 16
        body = self._shrink(body, max(budget - fixed, 200))
        used = fixed + self._tokens(body)
        hist = list(history)
        costs = [self._tokens(m["content"]) + 8 for m in hist]
        while hist and used + sum(costs) > budget:  # drop the oldest (user, assistant) pair
            hist, costs = hist[2:], costs[2:]
        last = f"{notes}\n\n{body}" if notes else body
        return [{"role": "system", "content": system}, *hist, {"role": "user", "content": last}]

    # ---------- answering ----------
    def remember_statements(self, text: str) -> list[int]:
        """Learn from plain chat: each statement the user makes (not a question)
        is stored on its own, labelled as told by the user. Splitting by sentence
        keeps each fact easy to find later. A long paste (an article, a log) is not
        a list of facts about the user: it is stored as unverified document chunks."""
        sentences = split_statements(text)
        if len(sentences) > self.max_auto_statements or len(text) > self.max_auto_chars:
            return ingest_text(self.memory, text, source="chat-paste", trust="unverified")
        if not sentences:
            return []
        return self.memory.add_many(sentences, kind="statement", source="user", trust="verified")

    def ask(self, question: str, max_tokens: int = 512) -> str:
        self.remember_statements(question)
        # The embedder reads only the start of a long text anyway (bge: 512 tokens).
        mems = self.memory.search(question[:4000], k=self.top_k, min_similarity=self.min_similarity)
        self.last_used_ids = [m.id for m in mems]
        body = f"Question: {question}"
        if PERSONAL.search(question[-500:]):
            body += "\n" + NO_GUESS
        # Notes go next to the question: small models use them far more reliably there.
        messages = self._build_prompt(SYSTEM, self.history[-2 * self.max_history_turns:],
                                      format_memories(mems), body, max_tokens)
        answer = self.core.chat(messages, max_tokens=max_tokens).strip()
        self.history += [{"role": "user", "content": question}, {"role": "assistant", "content": answer}]
        # Keep the exchange as an unverified answer: not searchable until approved with good().
        self.last_answer_id = self.memory.add(
            f"Q: {question[:2000]}\nA: {answer}", kind="answer", source="model", trust="unverified"
        )
        self.memory.save()
        return answer

    # ---------- thinking loop with a checker ----------
    def solve_code(self, task: str, tests: str | None = None) -> CodeResult:
        mems = self.memory.search(task[:4000], k=self.top_k, min_similarity=self.min_similarity)
        self.last_used_ids = [m.id for m in mems]
        request = task + (f"\n\nYour code must pass these tests:\n```python\n{tests}\n```" if tests else "")
        notes = format_memories(mems)
        code, check, errors = "", CheckResult(False, bool(tests), ""), []
        attempts, body = 0, request
        for attempts in range(1, self.max_fix_rounds + 1):
            # Each round sees the task, the last attempt and its error only, so the
            # prompt stays the same size however many rounds there are.
            messages = self._build_prompt(CODE_SYSTEM, [], notes, body, 1024)
            reply = self.core.chat(messages, max_tokens=1024, temperature=0.2)
            code = extract_code(reply)
            check = run_python(code, tests, timeout=self.code_timeout_s)
            if check.passed:
                break
            errors.append(check.output.strip().splitlines()[-1] if check.output.strip() else "failed")
            body = (f"{request}\n\nThis attempt failed:\n```python\n{code}\n```\nError:\n```\n"
                    f"{check.output[-2000:]}\n```\nFix it. Reply with the full corrected code block only.")

        mem_id = None
        if check.passed:
            lesson = f"Task: {task}\nWorking solution:\n```python\n{code}\n```"
            if errors:
                lesson += "\nMistakes fixed on the way: " + "; ".join(errors)
            # Verified only if real tests were run (CLAUDE.md rule).
            trust = "verified" if check.tested else "unverified"
            mem_id = self.memory.add(lesson, kind="lesson", source="checker", trust=trust)
            self.last_answer_id = mem_id
            self.memory.save()
        return CodeResult(code=code, check=check, attempts=attempts, memory_id=mem_id)

    # ---------- teaching ----------
    def teach(self, fact: str, protected: bool = False) -> int:
        mid = self.memory.add(fact, kind="fact", source="user", trust="verified", protected=protected)
        self.memory.save()
        return mid

    def correct(self, correction: str) -> int:
        """Mark the last answer wrong and save the correction. Notes that fed the wrong
        answer and say nearly the same thing as the correction (e.g. "My car is a Toyota"
        vs "My car is a Honda") are marked wrong too, or both would keep being retrieved.
        They are kept in the database (`last_demoted_ids`), never deleted."""
        self.last_demoted_ids = []
        if self.last_answer_id is not None:
            self.memory.mark_wrong(self.last_answer_id)
            self.memory.feedback(self.last_answer_id, -1)
        for m in self.memory.similar(correction, self.last_used_ids):
            if m.similarity >= self.conflict_similarity and m.trust != "wrong":
                self.memory.mark_wrong(m.id)
                self.last_demoted_ids.append(m.id)
        mid = self.memory.add(correction, kind="correction", source="user", trust="verified")
        if self.history and self.history[-1]["role"] == "assistant":
            self.history.append({"role": "user", "content": f"Correction: {correction}"})
            self.history.append({"role": "assistant", "content": "Understood, I have saved that correction."})
        self.memory.save()
        return mid

    def good(self):
        """The user approves the last answer: it becomes verified and reusable."""
        if self.last_answer_id is not None:
            self.memory.set_trust(self.last_answer_id, "verified")
        for mid in ([self.last_answer_id] if self.last_answer_id else []) + self.last_used_ids:
            self.memory.feedback(mid, +1)
        self.memory.save()

    def bad(self):
        for mid in ([self.last_answer_id] if self.last_answer_id else []) + self.last_used_ids:
            self.memory.feedback(mid, -1)
        self.memory.save()
