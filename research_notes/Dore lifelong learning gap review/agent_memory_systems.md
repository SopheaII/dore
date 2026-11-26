# Long-term memory systems for LLM agents and coding assistants (late-2026 view), compared with dore

Legend: ✅ = read in a primary or near-primary source during this session (2026-11-25). ⚠️ = from prior knowledge or a secondary or vendor source, not checked again this session. Check it before quoting it as fact. Vendor benchmark numbers are self-reported unless marked otherwise.

## Q1. How does each system extract, update, consolidate, forget, organise and retrieve?

### Takeaway
Almost every major system uses an LLM to extract memories and to resolve conflicts. The main differences are in how memory is organised: flat facts plus a vector index (Mem0), a temporal knowledge graph (Zep/Graphiti, Cognee, Mem0g), self-edited memory blocks with paging (Letta/MemGPT), linked notes (A-MEM), OS-style tiers (MemOS/MemoryOS), or a user profile (Memobase, ChatGPT). Coding assistants have moved toward plain markdown files that the agent itself writes (Claude Code auto memory, Letta Code MemFS ⚠️, and Cursor folding Memories into Rules). The 2026 trend is away from "LLM decides UPDATE/DELETE" and toward "add everything, keep validity or time metadata, and sort it out at retrieval time" (Mem0 2026 ADD-only; Zep edge invalidation; StateMem's deterministic supersession graph).

### Cited Findings

**Mem0 (2025 paper, arXiv:2504.19413)** ✅
- Extraction: an LLM function takes a conversation summary S (refreshed asynchronously), the last m=10 messages and the new message pair, and outputs candidate "salient facts". — [Mem0 paper (HTML)](https://arxiv.org/html/2504.19413v1)
- Update: for each candidate fact it retrieves the top s=10 similar memories. The LLM then picks ADD / UPDATE / DELETE / NOOP through a function-calling tool call. DELETE removes memories contradicted by new information. — [Mem0 paper](https://arxiv.org/html/2504.19413v1)
- The graph variant Mem0g uses an LLM update resolver that marks obsolete relationships as *invalid* instead of deleting them, which enables temporal reasoning. — [Mem0 paper](https://arxiv.org/html/2504.19413v1)
- Memory footprint: about 7k tokens per conversation (Mem0) and about 14k (Mem0g), against more than 600k for Zep's graph and about 26k for the raw conversation. Retrieved context per query: 1,764 tokens (Mem0), 3,616 (Mem0g), 3,911 (Zep), 26,031 (full context). — [Mem0 paper](https://arxiv.org/html/2504.19413v1)

**Mem0 2026 algorithm (April 2026)** ✅ (vendor page)
- Changes: (1) single-pass, **ADD-only** extraction in one LLM call, with no UPDATE or DELETE, so memories accumulate instead of being overwritten; (2) agent-confirmed facts stored "with the same weight as user-supplied facts"; (3) entity extraction, embedding and linking; (4) multi-signal retrieval that runs semantic, BM25 and entity matching in parallel and fuses the results. — [Mem0 blog, "AI memory benchmarks in 2026"](https://mem0.ai/blog/ai-memory-benchmarks-in-2026)
- Note for dore: point (2) is the opposite of dore's trust rule, where an agent-written note never overrules a user's verified fact.

**Zep / Graphiti (arXiv:2501.13956, Jan 2025)**
- Graphiti is "a temporally-aware knowledge graph engine" that combines conversational and structured business data and keeps historical relationships. ✅ — [Zep paper abstract](https://arxiv.org/abs/2501.13956)
- Zep attaches valid-time intervals to knowledge-graph edges and invalidates an edge when it detects a contradiction, so it can track whether a fact is still valid. ✅ (described by a third party) — [StateMem paper, Related Work](https://arxiv.org/pdf/2608.19652)
- ⚠️ Details from prior knowledge: a bi-temporal model (event time t_valid/t_invalid plus ingestion time); episode, semantic-entity and community subgraphs; LLM-based entity and edge extraction with entity resolution; hybrid retrieval (cosine + BM25 + graph breadth-first search) with rerankers (RRF, MMR, node distance, cross-encoder). — [Zep paper HTML](https://arxiv.org/html/2501.13956v1), [Graphiti repo](https://github.com/getzep/graphiti)

**Letta / MemGPT**
- Memory blocks: learned context is written to memory blocks, which several agents can share. ✅ (search snippet) — [Letta blog: memory blocks](https://letta.com/blog/memory-blocks)
- Sleep-time agents: a background agent shares memory with the primary agent and edits its memory blocks asynchronously. Shipped in Letta 0.7.0. ✅ (search snippet) — [Letta sleep-time docs](https://docs.letta.com/guides/agents/architectures/sleeptime/index.md), [Letta sleep-time compute blog, 21 Apr 2025](https://letta.com/blog/sleep-time-compute)
- ⚠️ 2026: Letta Code reportedly became the flagship on 16 Mar 2026. Memory moved to git-backed "context repositories" (MemFS) that general tools such as bash edit, and sleep-time work moved to client-side subagents. Source is a single wiki page marked "human editorial review pending". — [Latent Space wiki: Letta](https://latent.space/wiki/letta-ai-558a42a5/)
- ⚠️ Original MemGPT design (prior knowledge): core memory sits in context and the LLM edits it with tool calls; recall memory holds the searchable message history; archival memory is a vector store; the LLM itself pages data in and out. — [MemGPT arXiv:2310.08560](https://arxiv.org/abs/2310.08560)

**A-MEM (Xu et al., 2025)** ⚠️
- Zettelkasten-style notes. An LLM writes each note's keywords, tags and context description, links it to related older notes, and "evolves" those older notes' attributes when new notes arrive. Retrieval is by embedding. — [A-MEM arXiv:2502.12110](https://arxiv.org/abs/2502.12110)
- Independent cost measurement: 15.00 h construction time, 1.486M tokens and 1.181 s user latency. The authors say this suggests "super-linear update complexity". ✅ — [Anatomy of Agentic Memory, arXiv:2602.19320, Table 5](https://arxiv.org/html/2602.19320)

**LangMem (LangChain)** ⚠️
- An SDK with LLM-driven "memory managers" that extract, update and remove semantic memories (collections or profiles), episodic memories and procedural memory. The procedural part is prompt optimisation that rewrites the system prompt from feedback. It can run in the background as a "reflection" step. — [LangMem docs](https://langchain-ai.github.io/langmem/)
- On LoCoMo (in Mem0's harness), the J score was 58.10 and the p95 search latency 59.82 s, the slowest system tested. ✅ — [Mem0 paper](https://arxiv.org/html/2504.19413v1)

**Cognee** ⚠️
- An "ECL" (extract, cognify, load) pipeline. An LLM extracts entities and relations into a knowledge graph plus vector store; "memify" and enrichment steps run afterwards; retrieval combines graph and vector search. — [cognee GitHub](https://github.com/topoteretes/cognee)

**MemOS (MemTensor, 2025) and MemoryOS (BAI-LAB, 2025)** ⚠️
- MemOS treats memory as an OS resource. Its "MemCube" unit carries metadata (provenance, versioning), and the system schedules plaintext, activation (KV-cache) and parametric (LoRA) memory. — [MemOS arXiv:2507.03724](https://arxiv.org/abs/2507.03724)
- MemoryOS has short, mid and long-term tiers with heat-based promotion and paging, plus a user-persona store. — [MemoryOS arXiv:2506.06326](https://arxiv.org/abs/2506.06326)
- Independent measurement of MemoryOS: 32.372 s total user latency, 7.83 h construction, 4.043M tokens. Its "strict hierarchical paging" was judged "impractical for interactive settings". ✅ — [arXiv:2602.19320](https://arxiv.org/html/2602.19320)

**Memobase** ⚠️
- Profile-first memory. An LLM fills a user profile schema (topic/subtopic slots) and an event timeline from buffered chats, processed in batches when the buffer fills. Retrieval returns the profile and recent events, not a vector top-k. — [memobase GitHub](https://github.com/memodb-io/memobase)

**Claude Code (CLAUDE.md + auto memory)** ✅
- Two systems. CLAUDE.md is written by the user and loaded in full every session. Auto memory is "notes Claude writes itself based on your corrections and preferences", one directory per git repository (shared across worktrees), machine-local, on by default in local sessions. — [Claude Code docs: memory](https://code.claude.com/docs/en/memory.md)
- Four note types in frontmatter: `user`, `feedback`, `project`, `reference`. Claude skips anything it can derive from the code or that CLAUDE.md already says, and "doesn't save something every session". — [Claude Code docs](https://code.claude.com/docs/en/memory.md)
- Organisation: a `MEMORY.md` index, one line per memory, of which the first 200 lines or 25KB load at session start. Topic files are read on demand with ordinary file tools, so there is no vector search. Near the limit, Claude Code reminds Claude to "merge or drop stale entries". This is LLM-driven consolidation, triggered by a size check. — [Claude Code docs](https://code.claude.com/docs/en/memory.md)
- Memory files are exempt from transcript cleanup and stay until the user or Claude edits or deletes them. Claude can delete notes, which differs from dore's never-delete rule. — [Claude Code docs](https://code.claude.com/docs/en/memory.md)
- CLAUDE.md and auto memory are "context... not enforced configuration". Contradictory instructions may be resolved "arbitrarily", and `/doctor prompt-audit` (v2.1.283+) finds conflicts. — [Claude Code docs](https://code.claude.com/docs/en/memory.md)

**ChatGPT memory** ✅ (help-centre snippets)
- Two layers: "saved memories", kept until deleted, and "reference chat history", which draws on past chats. Details from past chats "can change over time as ChatGPT updates what's more helpful to remember". Deleting a chat does not delete a saved memory made from it. — [OpenAI Help: memory FAQ](https://help.openai.com/en/articles/8590148-memory-faq), [OpenAI Help: how memory uses past conversations](https://help.openai.com/en/articles/10303002-how-does-memory-use-pastconversations)
- A newer system "updates memories automatically" by importance, and users can switch back to legacy saved memories. Rollout scope is described inconsistently across help pages. — [OpenAI Help](https://help.openai.com/en/articles/8590148-memory-faq)

**Cursor / Windsurf**
- Cursor removed the Memories UI in 2.1.17 (Nov 2025) and told users to export memories into Rules. A later staff reply (Jan 2026) said the feature still works and only its management UI was removed. Automations and Projects have their own scoped memory, but regular Agent chats do not. ✅ (forum, conflicting staff statements) — [Cursor forum: memories gone in 2.1](https://forum.cursor.com/t/custom-modes-and-memories-gone-in-2-1/143744), [Cursor forum: memory tool disappeared](https://forum.cursor.com/t/memory-tool-dissapeared/148405)
- ⚠️ Windsurf (Cascade) auto-generates "Memories" with the LLM, alongside user-written rules. Not checked again for 2026. — [Windsurf docs: memories](https://docs.windsurf.com/windsurf/cascade/memories)

**Notable 2025–2026 newcomers** (all vendor claims ⚠️ unless noted)
- StateMem (UIUC, Aug 2026): a state-first method with a **deterministic, LLM-free pass over a dependency graph** that tracks supersession. It can wrap existing memory backends. ✅ — [arXiv:2608.19652](https://arxiv.org/pdf/2608.19652)
- STALE (Chao et al. 2026): propagates updates through an LLM adjudicator over a predefined schema. ✅ (as described by StateMem) — [arXiv:2608.19652](https://arxiv.org/pdf/2608.19652)
- MemSkill, SimpleMem, Nemori and MAGMA were measured independently in the "Anatomy" paper (see Q4). ✅ — [arXiv:2602.19320](https://arxiv.org/html/2602.19320)
- Other self-reported 2026 claims: ByteRover, EverMemOS, ZeroMemory, Dakera (no LLM reranking), Exabase M-1 (96.4% LongMemEval with Gemini 3 Flash, press release), and Supermemory. ⚠️ — [Mem0 2026 benchmark page](https://mem0.ai/blog/ai-memory-benchmarks-in-2026), [HPCwire/Exabase](https://www.hpcwire.com/off-the-wire/exabase-achieves-highest-reported-score-on-leading-ai-memory-benchmark-using-a-smaller-cheaper-model/)
- MemReader (arXiv:2604.07877) moves extraction from "passive to active" (title only seen). ⚠️ — [arXiv:2604.07877](https://arxiv.org/pdf/2604.07877)

**Surveys**
- "Anatomy of Agentic Memory" groups systems into four structures: lightweight semantic (vector top-k), entity-centric/personalised (attribute-value profiles), episodic/reflective (consolidated summaries), and structured/hierarchical (graphs, multi-tier). ✅ — [arXiv:2602.19320](https://arxiv.org/html/2602.19320)
- Other surveys found but not read: [Memory in the Age of AI Agents, arXiv:2512.13564](https://arxiv.org/abs/2512.13564v2); [Rethinking Memory Mechanisms of Foundation Agents, arXiv:2602.06052](https://arxiv.org/abs/2602.06052); [Graph-based Agent Memory survey, arXiv:2602.05665](https://arxiv.org/abs/2602.05665); [Memory for Autonomous LLM Agents, arXiv:2603.07670](https://arxiv.org/html/2603.07670).

### Comparison table (✅/⚠️ per the cited rows above)

| System | Extraction | Conflict / update | Consolidation | Forgetting | Organisation | Retrieval |
|---|---|---|---|---|---|---|
| Mem0 (2025) | LLM | LLM ADD/UPDATE/DELETE/NOOP | async summary | DELETE (hard) | vector (+graph in Mem0g) | vector top-k |
| Mem0 (2026) | LLM, single pass | ADD-only; accumulate | — | none described | vector + entity links | semantic + BM25 + entity fusion |
| Zep/Graphiti | LLM entities/edges | edge invalidation with validity times | community summaries ⚠️ | invalidate, keep history | temporal KG | hybrid + graph + rerank ⚠️ |
| Letta/MemGPT | the agent LLM itself (tool calls) | the LLM rewrites blocks | sleep-time agent | LLM decides | blocks + archival vector + recall | tools / search |
| A-MEM | LLM notes + links | LLM "memory evolution" | link evolution | — | linked notes | embedding |
| LangMem | LLM managers | LLM update/remove | background reflection ⚠️ | LLM removal ⚠️ | collections / profiles | vector |
| MemOS / MemoryOS | LLM | versioning ⚠️ / heat ⚠️ | tier promotion | paging out | OS tiers | tiered |
| Memobase | LLM, batched | profile slot overwrite ⚠️ | batch | — | profile + events | profile dump |
| Claude Code auto memory | Claude (main model) | Claude edits files | size-triggered rewrite | Claude may delete | markdown index + topic files | index in prompt; read files on demand |
| ChatGPT | LLM | "updates what's more helpful" | automatic (new system) | user delete | saved memories + chat history | not documented |
| **dore** | **spaCy grammar rules (no LLM)** | **newer wins; trust levels; keep the replaced note** | **recheck archives notes that today's rules would not store** | **archive, never delete** | **SQLite + FAISS, project/general scope** | **hybrid search, hook at 0 tokens** |

### Inferences
- dore is unusual in using no LLM in the learning path. Of the systems reviewed, only StateMem's deterministic supersession pass and Dakera's no-LLM reranking are LLM-free, and both cover only part of the pipeline. dore's "keep replaced notes, newer wins" matches the 2026 convergence (Zep invalidation, Mem0g invalid-marking, Mem0 2026 ADD-only, StateMem supersession).
- dore's trust levels (user-verified beats agent) appear in none of the systems above as an explicit rule. Mem0 2026 deliberately gives agent facts equal weight.

### Gaps
- I did not read the full Zep paper, the A-MEM, LangMem, Cognee, MemOS, MemoryOS or Memobase docs, or the Windsurf docs this session, so their rows rely on prior knowledge (⚠️).
- Letta's 2026 MemFS / Letta Code architecture is confirmed only by a single wiki page. Letta's sleep-time docs URL returned 404 on fetch.
- ChatGPT's internal extraction and retrieval mechanism is not publicly documented.

## Q2. Which systems use reflection or consolidation steps?

### Takeaway
Reflection or consolidation is now standard in LLM-based systems: Generative Agents reflection, Letta sleep-time agents, Mem0's async summary, LangMem background reflection, Claude Code's size-triggered index rewrite, and ChatGPT's automatic memory updates. All of them spend LLM tokens. Independent measurement shows consolidation and maintenance cost is often hidden from benchmarks and can make memory go stale.

### Cited Findings
- Letta sleep-time agents edit the primary agent's memory blocks asynchronously, in the background. ✅ (snippet) — [Letta docs](https://docs.letta.com/guides/agents/architectures/sleeptime/index.md), [Letta blog](https://letta.com/blog/sleep-time-compute). The paper is "Sleep-time Compute" (Lin et al., 2025). ⚠️ — [arXiv:2504.13171](https://arxiv.org/abs/2504.13171)
- Mem0 refreshes a conversation summary S asynchronously and feeds it to extraction. ✅ — [Mem0 paper](https://arxiv.org/html/2504.19413v1)
- Claude Code reminds Claude to "merge or drop stale entries" when `MEMORY.md` nears 200 lines or 25KB, and returns an error over the limit. ✅ — [Claude Code docs](https://code.claude.com/docs/en/memory.md)
- Generative Agents (Park et al., 2023): a memory stream scored by recency, importance and relevance, with periodic "reflections" (higher-level inferences) written back into memory. ⚠️ — [arXiv:2304.03442](https://arxiv.org/abs/2304.03442)
- Maintenance costs are "mostly excluded" from cost tables because they run asynchronously. The authors warn that excessive maintenance can cause "throughput collapse", leaving memory stale. ✅ — [arXiv:2602.19320](https://arxiv.org/html/2602.19320)
- ACE names two failure modes of LLM rewriting or summarising of context: "brevity bias" (domain detail dropped for concise summaries) and "context collapse" (repeated rewriting erodes detail). ✅ — [ACE arXiv:2510.04618](https://arxiv.org/abs/2510.04618)

### Inferences
- dore's planned idle-time "forgetting/merge" step (roadmap 3) is the analogue of sleep-time compute. ACE's context-collapse finding argues for dore's archive-not-rewrite approach: merging by rule and keeping the originals avoids the erosion that LLM summarisation causes.

### Gaps
- No public numbers were found on how often sleep-time consolidation introduces errors.

## Q3. Which systems learn procedures or skills rather than only facts?

### Takeaway
Procedural memory is the clearest capability gap between fact stores like dore and the 2025–2026 research frontier. ACE (evolving playbooks), ReasoningBank (strategies distilled from both successes and failures), Agent Workflow Memory, Voyager (skill library) and LangMem prompt optimisation all learn "how to do things" from execution feedback. All of them depend on an LLM to judge and distil.

### Cited Findings
- ACE treats context as "evolving playbooks" refined by a generation → reflection → curation cycle with "structured, incremental updates". It reports +10.6% on agent benchmarks and +8.6% on finance, works without labelled supervision (using execution feedback), and matches the top production agent on AppWorld with a smaller open model. ✅ — [ACE arXiv:2510.04618](https://arxiv.org/abs/2510.04618)
- ReasoningBank distils "generalizable reasoning strategies" from "self-judged successful and failed experiences". It beats memories that store raw trajectories or only successful routines on web-browsing and software-engineering benchmarks. MaTTS (memory-aware test-time scaling) amplifies the gains. ✅ (abstract; exact numbers not read) — [arXiv:2509.25140](https://arxiv.org/abs/2509.25140)
- Agent Workflow Memory induces reusable workflows from past trajectories (WebArena, Mind2Web). ⚠️ — [arXiv:2409.07429](https://arxiv.org/abs/2409.07429)
- Voyager keeps an ever-growing library of code skills, saved only after self-verification succeeds. ✅ (already in dore's REFERENCES.md) — [arXiv:2305.16291](https://arxiv.org/abs/2305.16291)
- LangMem has a procedural-memory mode that optimises the system prompt from feedback. ⚠️ — [LangMem docs](https://langchain-ai.github.io/langmem/)
- Claude Code recommends moving multi-step procedures from CLAUDE.md into skills or path-scoped rules. Procedural knowledge is hand-written, not learned. ✅ — [Claude Code docs](https://code.claude.com/docs/en/memory.md)
- MemSkill appears in the independent cost table (0.306 s latency, 0.60 h construction, 1.796M tokens). It was the fastest system measured. ✅ — [arXiv:2602.19320](https://arxiv.org/html/2602.19320)

### Inferences
- dore's roadmap step 2 found that the "failed command → similar success" signal gave junk lessons on 117 real sessions. ReasoningBank and ACE get their signal from an LLM judge plus task outcome. Without an LLM, dore would need a real checker (tests passing, exit codes) to label success. That matches dore's "only with a real checker" rule and Voyager's self-verification.

### Gaps
- Exact ReasoningBank numbers (WebArena, SWE-bench) and ACE's latency and cost reductions were not read (abstract only).

## Q4. Published accuracy and cost numbers (LoCoMo, LongMemEval, tokens, latency)

### Takeaway
The numbers are heavily disputed and not comparable across vendors. LoCoMo is small enough (~16–26k tokens) that full context beat Mem0 in Mem0's own paper (72.9 vs 68.4). About 6.4% of its answer key is wrong, and its GPT-4o-mini judge accepts 63% of vague wrong answers. LongMemEval-S is "borderline". Only LongMemEval-M (>1M tokens) and BEAM-1M/10M actually require memory. State tracking (updates) is a separate, weak capability across all systems.

### Cited Findings
**Mem0 paper LoCoMo (LLM-judge J, GPT-4o-mini, 2025)** ✅ — [Mem0 paper](https://arxiv.org/html/2504.19413v1)

| Method | J overall | Temporal | p95 search (s) | p95 total (s) |
|---|---|---|---|---|
| Full context | 72.90 | – | – | 17.117 |
| Mem0g | 68.44 | 58.13 | 0.657 | 2.590 |
| Mem0 | 66.88 | 55.51 | 0.200 | 1.440 |
| Zep (as run by Mem0) | 65.99 | 49.31 | 0.778 | 2.926 |
| Best RAG (k=2, 256-token chunks) | 60.97 | – | – | – |
| LangMem | 58.10 | 23.43 | 59.82 | 60.40 |
| OpenAI memory | 52.90 | 21.71 | – | 0.889 |
| A-Mem | 48.38 | 49.91 | 1.485 | 4.374 |

- Zep's rebuttal (6 May 2025, modified 3 Jun 2026) says Mem0 misconfigured Zep: both speakers were given the user role, timestamps were appended to messages instead of using `created_at`, and searches ran sequentially. Zep's corrected score is 75.14% ± 0.17 with 0.632 s p95 search. Zep also notes that full context (72.90) beats Mem0's best, and that LoCoMo lacks knowledge-update questions and has missing or wrong answers. ✅ — [Zep blog](https://www.getzep.com/blog/lies-damn-lies-statistics-is-mem0-really-sota-in-agent-memory/)
- Letta also said it could not reproduce the MemGPT setup in Mem0's evaluation. ⚠️ (secondary, Chinese-language) — [36kr](https://www.36kr.com/p/3423823155252610)
- Zep paper: DMR 94.8% vs MemGPT 93.4%; LongMemEval accuracy up to +18.5%; latency −90% vs baseline. ✅ (abstract) — [arXiv:2501.13956](https://arxiv.org/abs/2501.13956)
- Mem0 2026 algorithm (self-reported): LoCoMo 71.4 → 92.5; LongMemEval 67.8 → 94.4 (knowledge-update category 93.6, multi-session 88.0); BEAM-1M 64.1; BEAM-10M 48.6. About 7k tokens per retrieval, p50 latency 0.88–1.09 s. Full-context baselines use 25k+ tokens per query. ✅ (vendor) — [Mem0 2026 benchmarks](https://mem0.ai/blog/ai-memory-benchmarks-in-2026)
- Competitor claims on the same page, all self-reported and set up differently: Zep LoCoMo 94.7% (ByteRover measured Zep at 75.1%), Zep LongMemEval 71.2% (GPT-4o judge), ByteRover LoCoMo 92.2% or 96.1%, EverMemOS LoCoMo 92.3%. The page itself warns these "don't share a model stack, judge or retrieval configuration" and that "no public benchmark fully tests memory writes, forgetting, or per-user isolation". ✅ (vendor) — [Mem0 2026 benchmarks](https://mem0.ai/blog/ai-memory-benchmarks-in-2026)
- LoCoMo audit (Penfield, Apr 2026): 99 score-corrupting errors in 1,540 questions (6.4%). The gpt-4o-mini judge accepted 62.81% of deliberately wrong but topically adjacent answers. It caught specific wrong names or dates about 89% of the time. ✅ (independent blog) — [DEV: Penfield LoCoMo audit](https://dev.to/penfieldlabs/we-audited-locomo-64-of-the-answer-key-is-wrong-and-the-judge-accepts-up-to-63-of-intentionally-33lg)
- Context saturation: LoCoMo (~20k tokens) stays "comfortably in-window". LongMemEval-S (103k) is "borderline". LongMemEval-M (>1M) structurally needs memory. The authors propose Δ = Score_memory − Score_full-context as a diagnostic. ✅ — [arXiv:2602.19320](https://arxiv.org/html/2602.19320)
- Independent cost table (same paper): A-MEM 1.181 s / 15.00 h / 1.486M tokens; MemoryOS 32.372 s / 7.83 h / 4.043M; Nemori 1.129 s / 3.25 h / 7.044M; MAGMA 1.462 s / 7.28 h / 2.725M; SimpleMem 1.057 s / 3.45 h / 1.308M; MemSkill 0.306 s / 0.60 h / 1.796M. ✅ — [arXiv:2602.19320](https://arxiv.org/html/2602.19320)
- "Silent failure": Nemori's memory-write format-error rate goes from 17.91% (gpt-4o-mini) to 30.38% (Qwen-2.5-3B), and its answer score drops from 0.781 to 0.447. LLM-extraction quality collapses with small local models. ✅ — [arXiv:2602.19320](https://arxiv.org/html/2602.19320)
- State tracking (StateMemBench, 234 scenarios, Aug 2026): "state drift" means the right fact is in context but the agent acts on a stale version. The paper calls the task challenging for existing memory systems, RAG and long-context baselines. StateMem raises current-state accuracy from 0.205 to 0.363 (DeepSeek-V4-Flash) and 0.149 to 0.233 (Qwen-3.5-9B), and adds +32 to +67 points as a wrapper over six backends, of which +15 to +32 is attributed to state structure rather than added context. ✅ — [arXiv:2608.19652](https://arxiv.org/pdf/2608.19652)

### Inferences
- Absolute scores near 0.2–0.36 on state tracking mean that "newer wins" handling of updates is unsolved industry-wide. dore's own stale-note problem (reworded updates keep both notes, stale 7/11) is a known open problem, not a dore-specific failing. StateMem shows that a deterministic, LLM-free supersession layer can add large gains, which supports dore's design direction.
- A dore number on LoCoMo would mostly measure retrieval plus Claude, and would be confounded by the benchmark's flaws. LongMemEval knowledge-update questions or StateMemBench would be a fairer external check (estimate).

### Gaps
- No independent, same-harness comparison of Mem0 2026 / Zep 2026 / Letta was found.
- Token cost per write (extraction) is rarely reported per message. Mem0 reports retrieval tokens only.

## Q5. What LLM-based systems can do that a rules-only, no-LLM-extraction system cannot, and the reverse

### Takeaway
LLM extraction handles any wording, implicit facts, multi-hop and temporal inference, and the distilling of procedures from outcomes. These are exactly dore's measured weak spots (reworded updates, rephrased questions, Claude-side lessons). Rules-only gives near-zero cost and latency, determinism, privacy and resistance to the "silent failure" and "context collapse" modes of LLM writers. The 2026 literature suggests a hybrid: deterministic state and supersession structure over cheap extraction, with an LLM used only where a real checker exists.

### Cited Findings
- LLM write paths cost real tokens and time: 1.3M–7.0M tokens and 0.6–15 h to build memory on the benchmark (independent measurement). ✅ — [arXiv:2602.19320](https://arxiv.org/html/2602.19320)
- LLM writers fail silently with smaller models (Nemori format errors up to 30.38% on Qwen-2.5-3B), which matters for CPU-only local setups. ✅ — [arXiv:2602.19320](https://arxiv.org/html/2602.19320)
- LLM rewriting causes brevity bias and context collapse. ✅ — [ACE](https://arxiv.org/abs/2510.04618)
- LLM DELETE in Mem0 (2025) hard-deletes contradicted memories. Mem0 later moved to ADD-only (2026), and Mem0g and Zep invalidate instead of deleting. This is a convergence on dore's "never hard-delete". ✅ — [Mem0 paper](https://arxiv.org/html/2504.19413v1), [Mem0 2026](https://mem0.ai/blog/ai-memory-benchmarks-in-2026)
- Mem0 2026 gives agent-confirmed facts equal weight to user facts. dore's trust levels forbid this. ✅ — [Mem0 2026](https://mem0.ai/blog/ai-memory-benchmarks-in-2026)
- A deterministic, LLM-free supersession pass over a dependency graph (StateMem) improves state tracking across six backends. ✅ — [arXiv:2608.19652](https://arxiv.org/pdf/2608.19652)
- Hybrid retrieval (semantic + BM25 + entity) is the 2026 retrieval norm (Mem0 2026, Zep ⚠️). It needs no LLM at query time. ✅ — [Mem0 2026](https://mem0.ai/blog/ai-memory-benchmarks-in-2026)
- Claude Code auto memory uses the main model to write notes. That costs tokens inside the session, is not deterministic, and has no vector retrieval (index plus on-demand reads), but it captures `feedback` corrections and confirmed approaches. ✅ — [Claude Code docs](https://code.claude.com/docs/en/memory.md)
- Judge-based benchmarks reward vague, topical answers (62.81% acceptance), so the LLM systems' advantage on LoCoMo is partly a measurement artefact. ✅ — [Penfield audit](https://dev.to/penfieldlabs/we-audited-locomo-64-of-the-answer-key-is-wrong-and-the-judge-accepts-up-to-63-of-intentionally-33lg)

### Inferences

| Capability | LLM-extraction systems | dore (rules-only) |
|---|---|---|
| Any wording, implicit facts ("I'm moving to Berlin next month") | strong | limited to grammar shapes (estimate) |
| Reworded update recognised as the same slot | LLM matching (Mem0 2025), invalidation (Zep) | weak (stale 7/11, measured by dore) |
| Rephrased-question retrieval | query rewriting / entity links | 5/8 (measured by dore) |
| Procedural lessons from outcomes (ACE, ReasoningBank) | yes, with LLM judge | not adopted (junk without a checker) |
| Cost per write | LLM call(s); millions of tokens per benchmark build | ~0 tokens, spaCy on CPU |
| Latency in the prompt path | 0.2–60 s p95 search (Mem0 paper) | ~0.07 s hook (dore measured) |
| Determinism, auditability | low; silent format failures | high; same input gives the same notes |
| Privacy | most send text to a hosted LLM | fully local |
| Trust and provenance (user vs agent) | rarely explicit; Mem0 2026 treats them as equal | explicit verified / unverified / wrong |
| Never-delete history | converging (Zep, Mem0g, Mem0 2026) | yes |

- The strongest LLM-free additions suggested by this literature (inference): (1) StateMem-style explicit supersession and slot keys, to fix dore's reworded-update stale notes; (2) entity linking plus BM25 fusion in retrieval, as in Mem0 2026; (3) procedural notes only from checker-verified outcomes (tests or exit codes), as in Voyager.

### Gaps
- No published system was found that matches dore's full combination (no-LLM extraction, trust levels, project/general scope, Claude Code hooks at ~0 tokens). Absence of evidence is not proof that none exists.
- No head-to-head benchmark of a rules-only extractor against Mem0-style LLM extraction on the same data was found.
