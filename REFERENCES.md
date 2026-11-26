# References and prior work

dore is **not a new invention**. It combines ideas from existing research and projects into one small system that runs on a CPU laptop. This file credits where each idea comes from.

Model training was dropped (see `CLAUDE.md`): rows below about training (replay of old data, LoRA, PEFT) are kept as background only, not as parts of dore. What we could not find in prior work is the specific combination: a memory that learns from everyday use at ~0 LLM tokens, with trust levels, never-delete updates and project scope, designed for a normal laptop, and measured over months. Research moves fast, so something close may exist or appear.

Status column: ✅ = confirmed published work; ⚠️ = reported to us but not independently verified yet; check the source before citing.

## Where each part of dore comes from

| dore part | Borrowed idea | Source |
|---|---|---|
| Stable core + fast memory | Two learning systems: fast episodic store + slow general learner | Complementary Learning Systems (neuroscience); CFAM (robotics) |
| Fast memory (RAG) | Store knowledge outside the model, retrieve at answer time | RAG; ATLAS; Voyager's skill library; hippocampal indexing theory |
| Fast vector search | Hashing / approximate search to touch only what matters | SLIDE; FAISS |
| Thinking loop | Draft → check → improve repeatedly | Tiny Recursive Model (TRM); Voyager's iterative prompting |
| Self-checking | Only keep results that pass a real test | Voyager (self-verification); SEAL (downstream performance as reward) |
| Consolidation ("sleep") | Learn at several speeds; reorganise during idle time | Google Nested Learning / Hope (Titans); Letta sleep-time compute; sleep replay in the brain |
| Replay of old data | Mix old examples into new training to avoid forgetting | Sleep replay; continual-learning literature (EWC, generative replay) |
| Skills only, facts in memory | Fine-tuning on new facts increases hallucination | Gekhman et al. 2024 |
| LoRA add-on, not full training | LoRA learns less but forgets less | Hu et al. 2021; Biderman et al. 2024 |
| Never train on unchecked self-written text | Model collapse | Shumailov et al. 2024 |
| Forgetting, merging, scores | Active, useful forgetting; memory growth slows agents | Neuroscience of forgetting; Anthropic's long-running agent observations |
| Raw memory + consolidation (`memory.episodes`) | Keep a quick trace of everything, decide later what lasts; add everything, sort it out later | Hippocampal trace + selective consolidation (Kumaran et al. 2016; Rasch & Born 2013); Mem0 2026 ADD-only |

## AI research and projects

| Work | What dore takes from it | Status |
|---|---|---|
| **Voyager**: Wang et al., 2023, "An Open-Ended Embodied Agent with Large Language Models" ([arXiv:2305.16291](https://arxiv.org/abs/2305.16291)) | Ever-growing library of tested skills; save code only after it succeeds; retry with error feedback | ✅ |
| **Mem0 2026**, ADD-only extraction ([Mem0 blog, "AI memory benchmarks in 2026"](https://mem0.ai/blog/ai-memory-benchmarks-in-2026)) | Memories accumulate instead of being overwritten or deleted at write time; dore keeps every typed sentence as raw memory and lets idle-time consolidation decide (no LLM) | ✅ (blog post, seen in research notes 2026-11-25) |
| **Letta**, sleep-time compute: Lin et al., 2025 ([arXiv:2504.13171](https://arxiv.org/abs/2504.13171)) | Agents keep working during idle time to reorganise memory | ✅ |
| **SEAL**: Zweiger et al., 2025, "Self-Adapting Language Models" (MIT, [arXiv:2506.10943](https://arxiv.org/abs/2506.10943)) | Model writes its own fine-tuning data; keep updates that improve downstream performance | ✅ |
| **Nested Learning / Hope**: Google Research, Nov 2025; builds on **Titans** (Behrouz et al., 2025, [arXiv:2501.00663](https://arxiv.org/abs/2501.00663)) | Different parts learn at different speeds; surprise decides what to remember | ✅ |
| **Tiny Recursive Model (TRM)**: Jolicoeur-Martineau, Samsung SAIL Montréal, 2025 ([arXiv:2510.04871](https://arxiv.org/abs/2510.04871)) | A small model gets strong by looping and refining its answer | ✅ |
| **SLIDE**: Chen et al., MLSys 2020 ([arXiv:1903.03129](https://arxiv.org/abs/1903.03129)) | Smart algorithms (hashing to select few neurons) can beat bigger hardware on CPU | ✅ |
| **CFAM**: robotics continual-learning system, Sept 2026 | Frozen core plus a fast-growing memory after deployment | ⚠️ not verified |
| **ATLAS**: Nov 2025 | Teacher/student split with a persistent memory of distilled lessons, no weight updates | ⚠️ not verified |
| **Claude Plays Pokémon** (Anthropic) | Large memories slow agents down: they spend more time searching memory than acting | ⚠️ reported observation |
| **RAG**: Lewis et al., 2020 ([arXiv:2005.11401](https://arxiv.org/abs/2005.11401)) | Retrieval-augmented generation | ✅ |
| **LoRA**: Hu et al., 2021 ([arXiv:2106.09685](https://arxiv.org/abs/2106.09685)) | Train a small add-on instead of the whole model | ✅ |
| **EWC**: Kirkpatrick et al., 2017, PNAS ([arXiv:1612.00796](https://arxiv.org/abs/1612.00796)) | Protect important weights to reduce catastrophic forgetting | ✅ |

## Findings that set dore's hard rules

| Paper | Rule in dore |
|---|---|
| Gekhman et al., 2024, "Does Fine-Tuning LLMs on New Knowledge Encourage Hallucinations?" ([arXiv:2405.05904](https://arxiv.org/abs/2405.05904)) | Never train facts into the core; facts stay in memory |
| Biderman et al., 2024, "LoRA Learns Less and Forgets Less" ([arXiv:2405.09673](https://arxiv.org/abs/2405.09673)) | Use LoRA for safe, limited skill learning; expect a ceiling |
| Shumailov et al., 2024, "AI models collapse when trained on recursively generated data", *Nature* ([doi:10.1038/s41586-024-07566-y](https://doi.org/10.1038/s41586-024-07566-y)) | Never train on unchecked self-written text; always mix in real data |

## Neuroscience inspiration

| Idea | Source | Used in dore as |
|---|---|---|
| Complementary learning systems: fast hippocampus, slow neocortex | McClelland, McNaughton & O'Reilly, 1995, *Psychological Review* | Fast memory + stable core |
| Hippocampal indexing theory | Teyler & DiScenna, 1986 | Memory stores pointers/notes the core uses at answer time |
| Sleep replay and active systems consolidation | Buzsáki; Diekelmann & Born | Idle-time consolidation with replay |
| Fast specific trace first, selective consolidation later | Kumaran, Hassabis & McClelland, 2016, *Trends Cogn Sci* 20:512 ([PDF](https://web.stanford.edu/~jlmcc/papers/KumaranHassabisMcClelland16FinalMS.pdf)); Rasch & Born, 2013 ([PMC3768102](https://pmc.ncbi.nlm.nih.gov/articles/3768102)) | Raw memory of every typed sentence; the warm helper consolidates it while idle and judges it again when the rules change |
| Exemplar theory: categorise by similarity to stored examples | ⚠️ Medin & Schaffer, 1978; Nosofsky, 1986 (not opened) | Tried 2026-11-26 as a "lasting fact?" judge on bge-small vectors: rescued 0 facts, added junk; not used |
| Facts and "how to act" are different memories; procedural memory is the riskiest to write | CoALA: Sumers, Yao, Narasimhan & Griffiths, 2023 ([arXiv:2309.02427](https://arxiv.org/abs/2309.02427)) | A rule is a note marked as an instruction by its form; only evidence makes it come to mind unprompted |
| Procedures learned from feedback, not from one sentence | LangMem (LangChain), prompt optimisation from trajectories + feedback ([blog](https://blog.langchain.com/langmem-sdk-launch)); uses an LLM | dore: evidence at 0 tokens (said again in another session, practised by Claude) |
| Habits: context -> action links built by repetition, later cued by the context alone | Neal, Wood & Quinn, 2006; Wood & Neal, 2007, *Psychological Review* | Rules kept alive by practice; future: cue rules by the kind of work |
| Base-level activation: strength from each use, power-law fading, spacing effect | ACT-R: Anderson & Lebiere, 1998, *The Atomic Components of Thought*; Anderson & Schooler, 1991, *Psychological Science* 2:396 (power law of forgetting); ⚠️ Petrov, 2006, ICCM, approximation from count + first + last time (not opened) | Which rules come to mind at a session start (`memory.activation`) |
| Synaptic homeostasis hypothesis | Tononi & Cirelli | Score decay and pruning of low-value memories |
| Active, useful forgetting | Ryan & Frankland; Davis & Zhong (Rac1, dopamine) | Archive and merge instead of keeping every detail |
| Engrams and memory allocation | Tonegawa; Josselyn & Frankland | One fact per memory record, retrieved by similarity |
| Sparse coding, energy limits | Lennie, 2003 | Retrieve only the top few relevant memories |

Background reading used while designing dore: "How the Human Brain Works: From Golgi and Cajal to 2026 Discoveries, and Lessons for New AI" (research report, Nov 2026).

## Software used

| Tool | Role | Licence |
|---|---|---|
| [FAISS](https://github.com/facebookresearch/faiss) (Meta) | Vector search | MIT |
| [fastembed](https://github.com/qdrant/fastembed) (Qdrant) + [bge-small-en-v1.5](https://huggingface.co/BAAI/bge-small-en-v1.5) (BAAI) | Text embeddings | Apache-2.0 / MIT |
| SQLite | Memory records | Public domain |
| [spaCy](https://spacy.io/) + [en_core_web_md](https://spacy.io/models/en#en_core_web_md) (Explosion) | Sentence grammar: what is a lasting fact (`learn/grammar.py`) | MIT |
| PyTorch + PEFT *(dropped: no model training)* | LoRA training | BSD / Apache-2.0 |
