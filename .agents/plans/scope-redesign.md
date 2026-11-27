# Plan: redesign project vs general (scope)

Status (2026-11-26): **S1, S2, S3 (safe part) done**; S3 promotion by equal values and removing `ORG` measured as harmful (see `rules/memory-learning.md`); S4–S5 not started. Roadmap step 4 in `AGENTS.md` points here.
Rule it follows: **fix the design, not the example** (`AGENTS.md`).

## Why: what is weak today (checked in code and tests, 2026-11-26)

| # | Weakness | Where | Evidence |
|---|---|---|---|
| W1 | A project is the **folder name**. A subfolder becomes a separate project; a worktree (`.claude/worktrees/x`) is a separate project; two repos with the same folder name share notes; a renamed folder loses its notes | `hooks._project` | Real DB: a subfolder of this repo has its own "project" with 2 notes |
| W2 | Scope is decided **once, from one sentence's words**. The same fact in other words gets another scope | `statements.scope_for`, `ORG` word list | "**Our** staging server uses port 8443" -> general; "The staging port is now 9443" -> project |
| W3 | Only two levels: one project or everything. No level for "my company's repos" | schema `project` column | "our production server" is shared with every personal project too |
| W4 | An update in a project **replaces a general note everywhere**, while the new note lives only in that project. Other projects lose the fact | `store._supersede` | Stream test: "Ubuntu 24.04" lost in project blog; real test: staging port lost in project shop |
| W5 | A **cross-project fallback** (similarity >= 0.75, labelled) hides W4 and shows other projects' notes | `hooks.prompt_context` | Off: 1 question lost (the W4 one), tokens per work prompt 3.7 -> 2.8 (5 seeds) |
| W6 | Promotion to general only for value-less habits said with the **same content words** | `hooks._promoted` | "Our production server runs Ubuntu 22.04" said in 2 projects never becomes general |
| W7 | The user can't see or change a note's scope | — | dore saves silently |
| W8 | Facts said in the home folder are all general | `hooks._project` returns "" for home | A project fact typed in `~` reaches every project |

Prototype of a small fix for W4 + W5 (in memory, 5 seeds): correct weeks 3–4 26.2/26.0 -> 27.4/27.4 of 30,
repeat mistakes 6.4 -> 5.2, tokens 3.7 -> 2.8, `eval.conversation` unchanged. It shows the direction but is a
patch on `_supersede`; the design below makes it a consequence of one rule.

## Design

Keep three things apart. Today one `project` string does all three.

| | What | Decided by | Can change later? |
|---|---|---|---|
| **Where it was said** | repo, path inside it, session, date | facts (git, cwd) | never (provenance) |
| **What it is about** | the subject: the user, a shared thing, this repo's thing | grammar + the notes already known about that subject | yes, with evidence |
| **Who sees it** | the level the note lives at | computed from the two above | yes |

### Levels (most specific wins, like git config or Claude Code's own CLAUDE.md levels)

| Level | Meaning | Identified by |
|---|---|---|
| **user** | about the person (name, editor, how to answer) | grammar: the subject is the user (`grammar.about_user`, exists) |
| **workspace** | shared by one owner's or company's repos ("our production server") | git remote host + owner (`github.com/<owner>`); none without a remote |
| **repo** | one codebase | git common dir (worktrees and subfolders share it); without git, the full folder path (not its name) |
| **home** | sessions in `~` or `/` | its own level, seen only there (not general) |

### Rules

1. **Scope belongs to the subject, not the wording.** Each note has a subject key (`grammar.topic_key`, exists).
   A new statement about a subject that already has a note visible here goes to **that note's level**
   (an update stays where the fact lives). A new subject starts at the **repo** level, or **user** when the
   grammar says it is about the user.
2. **Explicit place words win** (closed class, grammar): "here", "in this repo/project", "locally" -> repo level,
   even when the subject has a broader note. "all my projects", "every project" -> user/workspace level.
3. **Updates replace only inside one level.** A narrower note **shadows** a broader note on the same subject in its
   own repo; the broader note stays for everyone else (no more W4).
4. **Promotion and demotion by evidence**, in idle consolidation (warm helper, exists), not at the prompt:
   - same subject, same value in 2+ repos of one workspace -> one workspace note (repo copies kept, linked);
   - same subject, same value in 2+ workspaces, and not a repo name/path/ID -> user level;
   - same subject with **different values** in different repos -> the subject is marked "per repo": never promoted;
   - replaces today's `_promoted` special case and the `ORG` word list.
5. **Reading:** candidates from repo + workspace + user (+ home only in home). For each subject keep the most
   specific level. **No similarity fallback to other repos.**
6. **User control:** `dore scope <id> user|workspace|repo` (CLI + MCP tool), and a correction like "that's for all
   my projects" right after a save moves the last note (same path as today's "No, ..." corrections).
7. **Migration:** old notes keep their folder name as an alias; `integrations.backfill` already reads session
   transcripts, which hold each session's `cwd`, so old folder names map to repo ids. No note is deleted by the move.

### Speed (estimates until measured)

| Part | Cost | How |
|---|---|---|
| Repo + workspace id | ~0.1 ms, est. | walk up to `.git`, read `.git` file / `commondir` / `config` as text; cache per folder in `hookd`. No `git` subprocess |
| Reading | ~0 ms extra, est. | same SQL with `level IN (...)`; subject grouping on <= k candidates |
| Writing | <1 ms, est. | subject lookup is an exact key match (index) |
| Promotion | 0 on the prompt path | idle consolidation, batches, low priority |

## Existing tools (to save building from scratch)

| Need | Tool | Status | Verdict |
|---|---|---|---|
| Repo identity | git's own files | — | Use directly; `pygit2`/`dulwich` not needed |
| Scope model | git config levels; Claude Code's CLAUDE.md levels; Mem0's `user_id`/`agent_id`/`run_id` filters | ideas | Borrow the model, no code |
| Facts that change over time | Graphiti (Zep): facts with valid-from / valid-to, never deleted | idea; needs an LLM + graph DB | Idea only (dore already has `valid_to`) |
| "Does the new fact update the old one?" | NLI model (tried 2026-11-26 for junk: 7 of 14 right) | rejected | No new AI models (user's choice): updates judged by evidence (S5) |
| Names and values in any case ("react", "vue") | GLiNER (an AI model) | rejected | No new AI models: use the parse and how the word is used in other notes |
| Split "X is A and Y is B" | spaCy (installed) | — | Build on the parse; `textacy` SVO (last release 2023) not worth a dependency |
| "…and it runs on RDS" | `fastcoref` (last release 2023) | stale | Skip; keep such sentences as one note |
| Synonym questions ("my job" -> "I work as a nurse") | rerankers (AI models) | measured 2026-11-26: half right, ~14 ms; rejected | No new AI models; roadmap step 5 |

## Steps (one at a time; each measured before the next)

| Step | Builds | Fixes | Measure |
|---|---|---|---|
| **S1** ✅ | Repo identity, home level, migration of old folder names (workspace level comes with S3) | W1, W8 | New cases: subfolder, worktree, two repos with the same name, home folder. Hook ms |
| **S2** ✅ | Subject-level scope on write, updates inside a level, shadowing; remove `ORG` list and the fallback | W2, W4, W5 | `eval.stream seeds 5`, `bench scale`, `eval.conversation`, `eval.learning` scope DEV/HELDOUT. Count labelled other-repo values as leaks from now on |
| **S3** | Promotion/demotion by evidence in consolidation (workspace, user); remove `_promoted` | W3, W6 | Org facts said in 2+ repos become shared; "per repo" subjects never leak |
| **S4** | `dore scope` CLI/MCP + "that's for all my projects" | W7 | Cases in `eval.learning` |
| **S5** | Updates judged by evidence: after a new value, the old note shown and not used by Claude, or corrected, is replaced | stale notes, synonym updates | 19 update cases, stream stale weeks 3–4 |
| then ✅ | One fact per note (split joined clauses), lowercase names (parse + how the word is used in other notes), leading side clauses ("Heads up,") by shape | lost half-facts, stale combined notes | DEV/HELDOUT junk must not rise |

New test set for every step: subfolder session, worktree session, two same-name repos in two workspaces, org fact
with and without "our", the same fact changed in other words in another repo, a repo that overrides a shared
value, a fact typed in the home folder.
