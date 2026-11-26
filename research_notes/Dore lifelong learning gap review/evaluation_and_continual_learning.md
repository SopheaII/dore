# Evaluation of lifelong agent memory and non-training continual learning (late-2026 view)

Notes collected 2026-11-25. Numbers marked ⚠️ come from memory of the papers or from a secondary summary and were not re-checked against the primary source in this session. Vendor-reported scores are labelled as such.

## 1. Benchmarks: what they test, top scores, typical failures

### Takeaway
Fact-recall chat benchmarks (LoCoMo, LongMemEval-S) are close to saturated in vendor claims (about 92-96%). They are also not comparable across vendors, because the judges and answer models differ. The hard, unsolved parts are **knowledge updates and selective forgetting** (multi-hop conflict resolution is at or below 7% for every method), **temporal ordering**, **not reusing obsolete memories**, and **memory that changes later behaviour or task success** rather than only recall. The 2026 benchmarks (MemoryArena, Memora/FAMA, TellOnce, PersonaCodeBench, Evo-Memory) move toward that last point. For coding agents, the closest match to dore is TellOnce: does a correction given once stop the same mistake later?

### Cited Findings
**LongMemEval (Wu et al., ICLR 2025)**
- It has 500 questions testing five abilities: information extraction (single-session user, assistant and preference questions), multi-session reasoning, knowledge updates, temporal reasoning (timestamps and time references), and abstention (30 false-premise questions that should get "I don't know") — [LongMemEval paper](https://arxiv.org/html/2410.10813v2)
- Sizes: LongMemEval-S is about 115k tokens (about 50 sessions) per question; LongMemEval-M is 500 sessions, about 1.5M tokens — [paper](https://arxiv.org/html/2410.10813v2)
- Commercial assistants on a 97-question subset: ChatGPT (GPT-4o) scored 0.577 and Coze 0.330, against 0.918 when GPT-4o reads the evidence offline. That is a 37% and a 64% drop. GPT-4o with the full long context fell from 0.870 (oracle evidence only) to 0.606, a 30% drop — [paper](https://arxiv.org/html/2410.10813v2)
- Failure modes the paper names: ChatGPT "overwrote crucial information" as chats went on (knowledge updates); Coze often did not record user facts that were given indirectly; memory designs that ignore time do poorly on temporal reasoning — [paper](https://arxiv.org/html/2410.10813v2)
- Design gains the paper measured:
  - Storing single rounds works better than storing whole sessions. Splitting into facts hurts overall QA through lost information but helps multi-session reasoning.
  - Fact-augmented keys (extracted user facts added to the index key) raised recall@k by 9.4% and QA accuracy by 5.4% on average.
  - Time-aware query expansion raised temporal recall by 6.8-11.3%, but only with a strong LLM doing the time extraction.
  - Chain-of-Note reading raised accuracy by up to about 10 points even with perfect retrieval.
  - Source: [paper](https://arxiv.org/html/2410.10813v2)
- Self-reported LongMemEval-S scores as of late 2026: Hindsight 94.6%, Mem0 94.4%, ByteRover 92.8%. Exabase claims 96.4% at top-50 retrieval, which is a different setting. These use different judges and answer models, so they are not comparable — [Vectorize explainer](https://vectorize.io/articles/longmemeval-explained); [Mem0 2026 benchmarks page](https://mem0.ai/library/agent-memory/ai-memory-benchmarks-in-2026); [HPCwire / Exabase press release](https://www.hpcwire.com/bigdatawire/this-just-in/exabase-achieves-highest-reported-score-on-leading-ai-memory-benchmark-using-a-smaller-cheaper-model/)
- Independent reproduction: Redis ran production memory systems on a shared GPT-4o backbone. Its best strategy reached 86.5%, averaged over task types — [Redis agent memory benchmark report](https://redis.io/agent-memory-benchmark-report/)
- The same system gets different numbers from different sources: Zep reports 71.2% on LongMemEval and a third party reports 75.1% — [Mem0 blog](https://mem0.ai/blog/ai-memory-benchmarks)
- LongMemEval-V2 exists, but its leaderboard was still "coming soon" — [LongMemEval-V2 page](https://xiaowu0162.github.io/longmemeval-v2/)
- I found no public per-ability leaderboard (knowledge updates, temporal reasoning, abstention) for top systems — [Vectorize](https://vectorize.io/articles/longmemeval-explained)

**LoCoMo (Maharana et al., ACL 2024)**
- ⚠️ It has very long dialogues (about 300 turns and about 9k tokens on average, up to 35 sessions) with QA categories for single-hop, multi-hop, temporal, open-domain and adversarial (unanswerable) questions — [LoCoMo paper](https://arxiv.org/abs/2402.17753)
- Letta's agent with only a plain file and grep, search and open tools scored 74.0% on LoCoMo with GPT-4o-mini. Mem0's best reported graph variant was 68.5%. Letta and Mem0 each dispute the other's method — [Letta blog, Aug 2025](https://www.letta.com/blog/benchmarking-ai-agent-memory)
- Mem0 reportedly claims 92.5% on LoCoMo after an April 2026 rewrite (not verified), and Zep claims 94.7% in 2026. One commentary notes that LoCoMo never scores knowledge updates — [Towards AI comparison](https://pub.towardsai.net/mem0-vs-zep-vs-letta-a-folder-of-text-files-shouldnt-beat-the-61k-star-memory-layer-9d7e65c5799c); [Mem0 2026 page](https://mem0.ai/library/agent-memory/ai-memory-benchmarks-in-2026)

**MemoryAgentBench (Hu, Wang, McAuley; ICLR 2026, arXiv v3 Mar 2026)**
- It tests four competencies through incremental multi-turn feeding:
  - Accurate Retrieval (datasets include EventQA and LongMemEval-S*)
  - Test-Time Learning (in-context classification on BANKING77, CLINC150 and similar sets, plus movie recommendation)
  - Long-Range Understanding (∞Bench-Sum, DetectiveQA)
  - Selective Forgetting, called "conflict resolution" in v1 (FactConsolidation single-hop and multi-hop, built from MQuAKE edit pairs)
  - Source: [MemoryAgentBench v3](https://arxiv.org/html/2507.05257v3)
- Selective forgetting, single-hop: GPT-4o 60.0, HippoRAG-v2 54.0, BM25 48.0, Claude-3.7-Sonnet 43.0, MemGPT 28.0, MIRIX 14.0. Multi-hop: 7 or lower for every method (GPT-4o 5.0, Claude-3.7 2.0) — [paper](https://arxiv.org/html/2507.05257v3)
- On a short 6K multi-hop version, o4-mini scored 80.0, falling to 14.0 at 32K. The task is solvable, but reasoning over long ranges breaks down — [paper](https://arxiv.org/html/2507.05257v3)
- RAG wins on accurate retrieval. Long-context models win on test-time learning (Claude-3.7 averages 53.9) and long-range understanding (Claude-3.7 averages 62.2). Agentic memory products are weak at test-time learning (MIRIX averages 24.1). No method masters all four — [paper](https://arxiv.org/html/2507.05257v3)

**MemBench and PerLTQA** (not re-checked this session)
- ⚠️ MemBench (Tan et al., ACL Findings 2025) separates factual memory from reflective memory (inferring preferences or high-level facts). It tests "participation" and "observation" scenarios and scores accuracy, recall, capacity and time efficiency — [MemBench arXiv](https://arxiv.org/abs/2506.21605)
- ⚠️ PerLTQA (Du et al., 2024) is a personal long-term memory QA set with semantic memory (profiles, relationships) and episodic memory (events, dialogues). Its tasks are memory classification, memory retrieval and memory synthesis, with about 8.6k questions — [PerLTQA arXiv](https://arxiv.org/abs/2402.16288)

**2026 benchmarks that measure use, change and forgetting**
- **MemoryArena** (ICML 2026) has interdependent multi-session tasks in four areas: web shopping, group travel with preferences, progressive search, and sequential maths and physics reasoning. Agents near the ceiling on LoCoMo do poorly here, so success on recall benchmarks does not carry over to agentic use — [MemoryArena site](https://memoryarena.github.io); [arXiv 2602.16313](https://arxiv.org/abs/2602.16313)
- A third-party run of MemoryArena with Qwen3-8B: BM25 reached 0.150 success on maths and 3.82% soft progress on travel. Every memory substrate tested scored low — [Harness the Memory, arXiv 2608.15008](https://arxiv.org/pdf/2608.15008)
- **Memora** (ACL 2026 Findings) covers weeks to months of personal conversations and tests remembering, reasoning and recommending. Its new metric, **FAMA (Forgetting-Aware Memory Accuracy)**, penalizes relying on obsolete or invalidated memories. Memory agents give only "marginal improvements." The main failures are reusing invalid memories and not reconciling memories that change over time — [arXiv 2604.20006](https://arxiv.org/abs/2604.20006)
- **TellOnce** (arXiv 2606.13174, v2 Oct 2026) measures whether a user's correction to a coding agent changes its later behaviour, as the rate of violated preference checks on later tasks with the learned rules frozen.
  - With Mem0, agents violated 57.5% of applicable preference checks, even though the corrections were stored.
  - TellOnce turns corrections into persistent, scoped, revisable rules (plus reusable checks). Against PGMem it cut violations by 19.3-42.3 points on ClawArena and 3.0-22.9 points on MemoryArena.
  - It also improved task quality on new coding tasks in SWE-Together.
  - Source: [TellOnce](https://arxiv.org/abs/2606.13174)
- **Evo-Memory** (Nov 2025) is a streaming benchmark over 10 datasets in sequential task streams, with more than 10 memory modules implemented. The agent must search, adapt and evolve its memory after each interaction. ReMem adds a "refine memory" action to ReAct. A baseline, ExpRAG, retrieves past task experiences — [arXiv 2511.20857](https://arxiv.org/abs/2511.20857)
  - ⚠️ ReMem reached 0.92 success on BabyAI with Gemini-2.5-Flash (third-party summary) — [alphaxiv](https://alphaxiv.org/abs/2511.20857)
- Other 2026 personalisation and coding benchmarks, seen only by title or reference, not read:
  - PersonaCodeBench: coding agents in persona-driven interactive sessions — [arXiv 2611.05739](https://arxiv.org/pdf/2611.05739)
  - PerMem-Bench / Personalize-then-Store: multi-year, multi-domain histories — [arXiv 2605.25535](https://arxiv.org/abs/2605.25535v1)
  - PERMA: event-driven preferences — [arXiv 2603.23231](https://arxiv.org/pdf/2603.23231)
  - CoReMem: memory for successive coding tasks — [arXiv 2611.17316](https://arxiv.org/pdf/2611.17316)
  - EvoMemBench (NeurIPS 2026): 15 memory methods against long-context baselines — [NeurIPS page](https://neurips.cc/virtual/2026/poster/139805)

### Inferences
- A good lifelong-memory evaluation in 2026 tests at least these abilities. dore's `bench stream` mapping is in brackets.
  1. **Extraction / recall** of stated facts [dore: *correct*]
  2. **Cross-session and cross-project aggregation** [partly: projects]
  3. **Knowledge updates / selective forgetting**, scored so that answering with the old value counts as an error, like Memora's FAMA [dore: *stale*]
  4. **Temporal reasoning**: "what did I use before X", ordering, relative dates [not tested by dore]
  5. **Abstention**: say nothing or "unknown" when no fact exists, and never fabricate [dore's *junk*/*leak* are related but not the same; there is no explicit "should inject nothing" score beyond hook silence]
  6. **Scoping / privacy**: a project fact never leaks to another project [dore: *leak*. No public benchmark scores this directly, so dore is ahead here.]
  7. **Behaviour change after correction**: the same mistake not repeated in later tasks, TellOnce-style [dore: *repeat*]
  8. **Test-time learning**: improving at tasks, not just recall [not tested by dore]
  9. **Cost**: tokens and latency per turn [dore: tokens per prompt, hook ms]
- dore's bench is synthetic and generated by its own authors, like LoCoMo and LongMemEval, which are LLM-generated. The main external-validity risk is wording. dore's current misses ("How long should your answers be?" vs "I prefer short answers") are exactly the paraphrase gap that LongMemEval's fact-augmented key expansion targets (+9.4% recall).
- Mainstream benchmarks are QA with an LLM judge. dore's "0 Claude tokens, rules-based" design cannot run a LongMemEval end to end without an answering model. dore could still report **retrieval recall@k on LongMemEval-S evidence sessions**, which needs no LLM, as an externally comparable number.
- The 57.5% violation rate for Mem0 in TellOnce suggests that storing a correction is not enough: injecting it at the right moment, as a scoped rule, matters. This supports dore's hook-time injection of rules, but dore currently measures "repeat" only on synthetic prompts.

### Gaps
- I found no per-ability public leaderboard for knowledge updates, temporal reasoning or abstention for top LongMemEval systems; vendors report only overall scores.
- I could not read the numeric results of PersonaCodeBench, PERMA, PerMem-Bench, CoReMem or SWE-Together. The search showed only titles and reference fragments.
- MemBench and PerLTQA details come from memory, not checked this session (⚠️).
- Memora's per-system FAMA numbers were not in the abstract.

## 2. Non-training continual learning approaches and their measured gains

### Takeaway
The working approaches without training all write natural-language or code memory outside the model and retrieve or inject it later:
- reflection (Reflexion)
- insight and experience extraction (ExpeL, ReasoningBank)
- reusable workflows and skills (Agent Workflow Memory, Voyager)
- evolving playbooks and rules files (ACE, TellOnce, Anthropic's memory tool)

Reported gains are moderate and real: about +5 to +10 absolute points on agent benchmarks, larger in relative terms. Gains hold best when the update is **incremental (itemised deltas), not a full rewrite**, and when it uses **execution or user feedback** as the signal.

### Cited Findings
- **ACE (Agentic Context Engineering, ICLR 2026)**
  - It treats context as an evolving "playbook" updated through generation, reflection and curation.
  - It reports +10.6% on agent benchmarks (AppWorld) and +8.6% on finance, with lower adaptation latency and rollout cost, and it works without labelled supervision, from natural execution feedback.
  - Source: [ACE arXiv 2510.04618](https://arxiv.org/abs/2510.04618)
- ACE names two failure modes of self-improving prompts: **context collapse** (repeated full rewrites erode details) and **brevity bias** (summaries drop domain insights) — [ACE](https://arxiv.org/abs/2510.04618)
  - Example of collapse: a Dynamic Cheatsheet context shrank from 18,282 to 122 tokens in one step, and accuracy fell from 66.7% to 57.1% — [Analytics Vidhya summary](https://www.analyticsvidhya.com/blog/2026/09/agentic-context-engineering/) ⚠️ (secondary source)
- ACE on DeepSeek-V3.1 matched the top AppWorld production agent (IBM-CUGA, GPT-4.1) on average and beat it on the harder test-challenge split. It was validated only on AppWorld and finance — [ACE](https://arxiv.org/html/2510.04618v2); [ACE ICLR page](https://iclr.cc/virtual/2026/poster/10008343)
- **ReasoningBank (Google, ICLR 2026)**
  - It distils generalisable reasoning strategies from both successful and failed trajectories, which the agent judges itself.
  - On WebArena it gave +8.3, +7.2 and +4.6 points over memory-free agents across three backbones.
  - On SWE-bench Verified it gave 34.2→38.8% (Gemini 2.5 Flash, average steps 30.3→27.5) and 54.0→57.4% (Gemini 2.5 Pro).
  - Memory-aware test-time scaling (MaTTS) added further gains.
  - Source: [ReasoningBank arXiv 2509.25140](https://arxiv.org/abs/2509.25140); [Google Research blog](https://research.google/blog/reasoningbank-enabling-agents-to-learn-from-experience/)
- **Agent Workflow Memory (ICML 2025)**
  - It induces reusable workflows from past trajectories.
  - Relative success gains: +24.6% on Mind2Web and +51.1% on WebArena, with fewer steps. It beat human-written workflows by 7.9%, and gained +8.9 to +14.0 absolute points on cross-website and cross-domain splits (generalisation).
  - Source: [AWM arXiv 2409.07429](https://arxiv.org/abs/2409.07429)
- **Reflexion** (Shinn et al., NeurIPS 2023): verbal self-reflection stored in an episodic buffer. ⚠️ 91% pass@1 on HumanEval vs 80% for the GPT-4 baseline; large gains on ALFWorld and HotpotQA. It relies on a real feedback signal (unit tests, environment reward) — [Reflexion arXiv 2303.11366](https://arxiv.org/abs/2303.11366)
- **ExpeL** (Zhao et al., AAAI 2024): extracts natural-language insights plus successful examples from training tasks, then recalls them at inference. ⚠️ It improves over ReAct on ALFWorld, HotpotQA and WebShop, and the insights transfer across tasks — [ExpeL arXiv 2308.10128](https://arxiv.org/abs/2308.10128)
- **Voyager** (2023): an executable code-skill library that grows through exploration and self-verification. ⚠️ It reports 3.3x more unique items and up to 15.3x faster tech-tree milestones than prior Minecraft agents — [Voyager arXiv 2305.16291](https://arxiv.org/abs/2305.16291)
- **TellOnce** (2026): user corrections become persistent, scoped, revisable rules, plus reusable checks. Violation rates were lowest in all six model-benchmark settings, task quality stayed comparable, and quality on new coding tasks improved — [TellOnce](https://arxiv.org/abs/2606.13174)
- **Anthropic memory tool and context editing** (vendor-reported): +39% over baseline on an internal agentic-search eval with memory tool plus context editing, and +29% with context editing alone. In a 100-turn eval, token use fell 84%. The memory is client-side files — [Anthropic context management announcement](https://www.anthropic.com/news/context-management)
- Anthropic's guidance: aim for "the smallest possible set of high-signal tokens"; "context rot" means recall falls as context grows — [Anthropic engineering: effective context engineering](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents)
- Tools-only memory: plain files plus grep reached 74% on LoCoMo, so simple memory can match specialised stores on recall — [Letta](https://www.letta.com/blog/benchmarking-ai-agent-memory)
- ⚠️ Mem0 paper (2025): about 26% relative gain over OpenAI memory on LoCoMo (LLM judge), with about 91% lower p95 latency and about 90% fewer tokens than full context — [Mem0 arXiv 2504.19413](https://arxiv.org/abs/2504.19413)
- Survey framing: memory splits by function into factual, experiential and working memory, and by dynamics into formation, evolution and retrieval — [Memory in the Age of AI Agents, arXiv 2512.13564](https://arxiv.org/abs/2512.13564)
  - Another survey names six atomic operations: consolidation, updating, indexing, forgetting, retrieval, compression — [Rethinking Memory in AI, arXiv 2505.00675](https://arxiv.org/abs/2505.00675)

### Inferences
- dore covers **factual memory** (user and project facts, corrections, rules) well. It mostly lacks **experiential and procedural memory**: lessons from task outcomes (ReasoningBank, ExpeL), workflows (AWM), skills (Voyager). Its roadmap step 2 tried learning from failed then successful shell commands and found junk. This matches the literature: ReasoningBank and AWM depend on a judge of success (an LLM self-judge or a task checker), which a 0-token rules system does not have.
- ACE's warning about context collapse supports dore's design of itemised notes, never deleted and only archived, over a rewritten summary file.
- TellOnce is the closest published analogue to dore's "repeat" metric and rules output. Its "scoped, revisable rules" and "reusable checks" map to dore's project scoping and rule notes.
- Reported gains are mostly measured with strong LLM backbones and LLM judges. Gains for a rules-only memory with no LLM in the loop are not covered by any paper I found.

### Gaps
- I found no measured result for non-training learning from *implicit* user acceptance ("yes, keep that"), which is dore's next signal.
- ExpeL, Reflexion and Voyager numbers are recalled, not re-fetched (⚠️).
- I found no independent replication of ACE outside AppWorld and finance.

## 3. Risks of growing memory and guards against them

### Takeaway
Growing memory brings five main risks:
- **poisoning** through normal queries (MINJA: more than 95% injection success)
- **stale or obsolete facts** reused (Memora, MemoryAgentBench selective forgetting)
- **self-reinforcing errors**, where the agent's own wrong conclusions are stored as experience
- **context bloat and rot**, alongside its opposite, **collapse**
- **privacy and scope leaks**

Guards that work in the literature: trust scores and provenance on notes, trust-aware retrieval, newest-wins with dated notes, scoped rules, incremental edits rather than rewrites, and pruning or archiving.

### Cited Findings
- **MINJA**: memory injection through query-only interaction. It averages 98.2% injection success and 76.8% attack success. Moderation (Llama Guard) and sanitisation were ineffective in the original paper — [MINJA arXiv 2503.03704](https://arxiv.org/html/2503.03704v5)
- A 2026 follow-up found that realistic conditions (existing legitimate memories) sharply reduce MINJA's effectiveness. It proposes composite trust scoring with input/output moderation, and memory sanitisation with **trust-aware retrieval**. Trust thresholds need calibrating to avoid both over-rejecting and missing attacks — [Memory Poisoning Attack and Defense, arXiv 2601.05504](https://arxiv.org/html/2601.05504)
- ⚠️ AgentPoison (NeurIPS 2024) puts trigger-optimised backdoors into RAG and memory stores. It assumes direct write access — [AgentPoison arXiv 2407.12784](https://arxiv.org/abs/2407.12784)
- Obsolete memories: Memora finds frequent reuse of invalid memories and failure to reconcile changing memories — [arXiv 2604.20006](https://arxiv.org/abs/2604.20006). In MemoryAgentBench, multi-hop selective forgetting is 7% or lower — [arXiv 2507.05257](https://arxiv.org/html/2507.05257v3)
- Overwriting: ChatGPT memory overwrote crucial information over long chats — [LongMemEval](https://arxiv.org/html/2410.10813v2)
- Context rot (recall degrades with more tokens), with the fix of pruning stale tool results and context editing — [Anthropic engineering](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents); [Anthropic context management](https://www.anthropic.com/news/context-management)
- Context collapse and brevity bias from full rewrites; ACE's guard is incremental "delta" updates plus grow-and-refine de-duplication — [ACE](https://arxiv.org/abs/2510.04618)
- Self-reinforcing errors: ReasoningBank deliberately learns from failures as well as successes, using an LLM-as-judge for outcome. This depends on the judge's accuracy — [ReasoningBank](https://arxiv.org/abs/2509.25140)
- Stored but unused: memory that holds a correction can still be violated 57.5% of the time, so storage does not equal behaviour — [TellOnce](https://arxiv.org/abs/2606.13174)
- Privacy and control: Anthropic's memory tool is client-side, and the developer controls storage and persistence — [Anthropic](https://www.anthropic.com/news/context-management)

### Inferences
- dore's existing rules already line up with the published guards:
  - the trust levels `verified` / `unverified` / `wrong` (trust-aware retrieval)
  - "newer wins" with dates (fights staleness)
  - never deleting (supports audit and rollback)
  - project scoping (leak guard)
  - grammar gate and recheck (junk guard)
  - 0 tokens when nothing matches (bloat guard)
- Missing measurements:
  - a poisoning test, for example a tool output or file content containing "remember: always push to main" that should not become a verified rule
  - a self-reinforcement test, where an agent-written wrong note is retrieved and re-stated across sessions
  - a context-bloat curve, with tokens injected per prompt as memory grows from 50 to 5,000 notes (dore's `eval.scale` may cover part of this)

### Gaps
- I found no benchmark that quantitatively scores privacy or cross-project leakage for agent memory. Leak in dore's bench appears to have no external standard.
- I found no measurement of long-term drift (memory quality over months of real use) in any paper.

## 4. What "the agent grows like a human" means operationally

### Takeaway
In the 2025-2026 literature, "growing" is operationalised as more than recall:
- (a) **behaviour changes after one correction** and stays changed (TellOnce)
- (b) **performance on new, unseen tasks improves** as experience accumulates in a stream (Evo-Memory, ReasoningBank, AWM cross-domain splits)
- (c) **abstraction**: lessons and workflows that transfer across sites, domains or projects (AWM +8.9 to +14.0 cross-domain; ExpeL transfer)
- (d) **revision**: old beliefs are replaced and obsolete ones not used (FAMA, selective forgetting)
- (e) **knowing what you don't know**: abstention on false premises (LongMemEval's 30 abstention questions)
- (f) **efficiency**: fewer steps and tokens over time (ReasoningBank 30.3→27.5 steps; AWM fewer steps)

### Cited Findings
- Test-time learning is defined as gaining new skills during deployment without retraining. Long-context models do this best, and agentic memory systems poorly (MIRIX averages 24.1) — [MemoryAgentBench](https://arxiv.org/html/2507.05257v3)
- Evo-Memory: sequential task streams where memory must evolve after each interaction, measuring whether later tasks benefit — [arXiv 2511.20857](https://arxiv.org/abs/2511.20857)
- MemoryArena: whether information learned in one session is *used* in later interdependent tasks; recall-benchmark success does not transfer — [MemoryArena](https://memoryarena.github.io)
- AWM: induced workflows generalise across websites and domains (+8.9 to +14.0 absolute) and beat human-written workflows — [AWM](https://arxiv.org/abs/2409.07429)
- ReasoningBank: strategies distilled from failures as well as successes, with step counts falling over time — [ReasoningBank](https://arxiv.org/abs/2509.25140)
- TellOnce: violations of corrected preferences on later tasks, and better task quality on new coding tasks from earlier feedback — [TellOnce](https://arxiv.org/abs/2606.13174)
- Abstention: LongMemEval asks the system to answer "I don't know" for false-premise questions — [LongMemEval](https://arxiv.org/html/2410.10813v2)
- Surveys separate factual, experiential and working memory (what you know, what you learned from doing, what you're holding now) — [arXiv 2512.13564](https://arxiv.org/abs/2512.13564)

### Inferences
- For dore, "grows like a human" can be turned into measurable bench items. In each, the score is what Claude does next, not only what the memory returns.
  1. **One-shot correction persistence**: correction in week 1; violation rate in weeks 2-4 on *differently worded* prompts.
  2. **Paraphrase generalisation**: the same fact asked in unseen wording. dore's current biggest miss is this: "How long should your answers be?" misses in all 4 weeks × 3 projects in the 2026-11-25 run.
  3. **Abstraction / promotion**: a habit seen in 2+ projects becomes general (roadmap step 4), scored on a held-out new project.
  4. **Revision**: FAMA-style scoring where returning the old value counts worse than returning nothing. dore's "stale" score is close; it could weight stale above miss.
  5. **Abstention**: prompts where no note should be injected (dore measures junk and tokens; it could add an explicit "should stay silent" precision).
  6. **Temporal**: "what did I use before Helix?", which dore keeps because it never deletes.
  7. **Task improvement**: fewer repeated failing commands per session over weeks, which needs a real checker per dore's rules.
- dore's bench run on 2026-11-25 (`stream_bench_output.txt`) shows misses on user-general preference questions (answer length, editor) in every week and project, plus project-fact updates in weeks 3-4 (port 3001, Cloudflare). This is the same pattern the literature reports: preference and paraphrase recall, then knowledge updates, are the weakest abilities.

### Gaps
- I found no standard metric for "human-like" growth. Each paper defines its own (violation rate, success on a task stream, transfer splits).
- I found no benchmark that uses real (not synthetic) multi-month coding-agent logs with ground truth. TellOnce builds its diagnostic from anonymised real interactions, but its dataset size was not visible.
