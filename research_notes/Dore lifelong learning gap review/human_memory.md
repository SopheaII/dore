# How humans learn and grow knowledge over time: design lessons for a non-training AI memory (dore)

Scope: cognitive science of memory framed as requirements for a database + retrieval memory (SQLite + FAISS notes, no training, never hard-delete, trust levels, newer wins). Researched 2026-11-25.
Marking: claims with a link were seen in a search result or a fetched page this session. Claims marked ⚠️ are background knowledge of well-known papers that were **not** opened this session; check them before quoting numbers.

---

## 1. Encoding: what gets remembered (attention, salience, emotion, repetition, prediction error)

### Takeaway
Humans do not store everything equally. They store more strongly what is surprising (prediction error), what is attended to after a confident mistake, what fits an existing schema, and what is repeated with spacing. A memory system should score each note at write time for "surprise vs what I already hold" and "was this a correction", not only "is this a fact-shaped sentence".

### Cited Findings
- Prediction errors (PEs) strengthen episodic encoding: in one incidental-memory study, encoding strength scaled with the reward prediction error at the moment the item was shown — [PMC6625913](https://pmc.ncbi.nlm.nih.gov/articles/PMC6625913)
- The effect is real but conditional: it depends on sign vs magnitude of the error, whether the participant's prediction was right or wrong, and arousal; mechanism still debated — [PMC6117220](https://pmc.ncbi.nlm.nih.gov/articles/PMC6117220); [npj Science of Learning 2023](https://www.nature.com/articles/s41539-023-00166-x.pdf)
- Kalbe & Schwabe: memory boost from aversive prediction errors stays after controlling for arousal (so it is surprise, not just emotion) — [Kalbe 2022 Cereb Cortex PDF](https://www.psy.uni-hamburg.de/arbeitsbereiche/kognitionspsychologie/publikationen/kalbe2022-cerebcortex.pdf)
- PEs promote *selective* encoding and consolidation of behaviourally relevant events (dissertation conclusion) — [Loock dissertation, Hamburg](https://ediss.sub.uni-hamburg.de/bitstream/ediss/11827/1/Dissertation_Loock.pdf)
- Hypercorrection effect: errors made with **high confidence** are more likely to be corrected after feedback than low-confidence errors (Butterfield & Metcalfe 2001); 2006 follow-up shows attention to feedback is heightened after confident errors (people missed a concurrent soft tone during that feedback) — [Butterfield & Metcalfe 2006, Metacognition and Learning](https://link.springer.com/article/10.1007/s11409-006-6894-z); [Metcalfe & Finn review, PMC3079415](https://pmc.ncbi.nlm.nih.gov/articles/PMC3079415)
- Boundary: low-confidence errors on trick questions were corrected as often as high-confidence ones (Griffiths & Higham) — [Southampton eprint](https://eprints.soton.ac.uk/412186/1/Beyond_Hypercorrection_manuscipt_R2_Final.docx)
- Generative Agents score "importance" (1–10, LLM-rated "poignancy") at write time and use it at retrieval — [Park et al. 2023, arXiv 2304.03442](https://arxiv.org/pdf/2304.03442)
- MemoryBank weighs "relative significance" of each memory alongside time — [Zhong et al. 2023/AAAI 2024, arXiv 2305.10250](https://arxiv.org/abs/2305.10250)
- ⚠️ Emotional arousal enhances consolidation via amygdala–hippocampus modulation (McGaugh, e.g. Annu Rev Neurosci 2004) — not fetched.

### Inferences
- For dore, the strongest "salience" signal available at ~0 tokens is not emotion but **correction / contradiction of an existing note** (a prediction error against memory). A user message that contradicts a stored note is exactly the high-PE, hypercorrection case: it should be stored with high priority and the old note demoted, which matches "newer wins". dore already treats corrections specially; the cognitive literature says this is the right place to concentrate effort.
- A cheap PE score: novelty = 1 − max cosine similarity to existing notes in the same scope; contradiction = high similarity + different value. Novel-but-unrelated text is weaker evidence of importance than "same slot, new value".
- Importance via an LLM rating (Generative Agents) costs tokens; dore's "decide by shape/grammar/meaning" constraint suggests structural proxies (explicit user imperative, "always/never", correction form, repetition across sessions) instead.

### Gaps
- No source found that measures which encoding signals predict *usefulness* of notes for coding agents specifically; would need dore's own `bench stream` data.

---

## 2. Consolidation: episodic -> semantic, sleep/offline replay, CLS, schemas

### Takeaway
Humans keep a fast, specific store (hippocampus, episodes) and a slow, general store (neocortex, semantic knowledge); offline replay (largely in sleep) gradually turns many episodes into general knowledge, and new facts that fit an existing schema are absorbed fast. The software analogue is a two-tier memory: raw session notes, plus an idle-time job that replays them, merges repeats into general notes, and links/promotes facts that recur.

### Cited Findings
- CLS (McClelland, McNaughton & O'Reilly 1995) updated by Kumaran, Hassabis & McClelland 2016 (Trends Cogn Sci 20:512–534): hippocampus learns fast and specific, neocortex slow and structured; consolidation is complete when neocortex can recall without hippocampus; speed of integration into neocortex depends on how well new info fits existing knowledge; replay ideas were implemented in DeepMind's DQN experience replay — [Kumaran et al. 2016 PDF](https://web.stanford.edu/~jlmcc/papers/KumaranHassabisMcClelland16FinalMS.pdf); [ScienceDaily summary](https://www.sciencedaily.com/releases/2016/06/160614133609.htm)
- ⚠️ Original CLS motivation: interleaved slow learning avoids catastrophic interference when new knowledge is added to a structured store (McClelland et al. 1995, Psychol Rev 102:419) — not fetched.
- Schemas: Tse et al. 2007 (Science 316:76–82): once rats had a schema, one-trial new associations became hippocampus-independent within ~48 h; without a stable schema, one-trial learning failed — [PubMed 17412951](https://pubmed.ncbi.nlm.nih.gov/17412951/); [full text PDF](https://confluence.cornell.edu/download/attachments/89461995/Tse_2007_Schemas%20and%20Memory%20Consolidation.pdf)
- Tse et al. 2011 found prefrontal gene activation during new paired-associate learning, challenging a strict fast-hippocampus/slow-cortex split — [Edinburgh research record](https://www.research.ed.ac.uk/en/publications/schema-dependent-gene-activation-and-memory-encoding-in-neocortex/)
- Sleep: theory shifted from sleep passively protecting memories to *active systems consolidation* — memories reactivated in slow-wave sleep and redistributed from hippocampus to cortex, and this is **selective**, not applied to all memories (Rasch & Born 2013; Born & Wilhelm) — [PMC3768102](https://pmc.ncbi.nlm.nih.gov/articles/3768102); [Inostroza & Born 2013 PDF](https://www.cse.iitk.ac.in/users/se367/14/Readings/papers/inostroza-born-13_sleep-for-transforming-episodic-memory.pdf)
- Repeated hippocampal replay in slow-wave sleep drives gradual transformation and integration of representations in neocortex — [Nature Neuroscience 2019 review](https://www.nature.com/articles/s41593-019-0467-3)
- Competing account: synaptic homeostasis hypothesis (sleep downscales synapses) vs active systems consolidation — [Feld & Born, PMC6879745](https://pmc.ncbi.nlm.nih.gov/articles/PMC6879745)
- "Resource reallocation": consolidation may free hippocampal capacity for next-day learning (treated as hypothesis) — [PMC7618826](https://pmc.ncbi.nlm.nih.gov/articles/PMC7618826)
- AI analogues: Generative Agents' reflection — triggered when summed importance of recent events exceeds 150 (~2–3 times per simulated day); agent asks questions about recent experience, retrieves memories for each, writes higher-level insights that can themselves be reflected on — [Park et al. 2023](https://arxiv.org/pdf/2304.03442)
- HippoRAG (NeurIPS 2024) uses hippocampal indexing theory (Teyler & Discenna): LLM = neocortex, a schemaless knowledge graph of OpenIE triples = hippocampal index; Personalized PageRank gives multi-hop retrieval in one step; reports up to 20% better multi-hop QA and 10–20x cheaper / 6–13x faster than IRCoT (v1 preprint says 10–30x cheaper) — [arXiv 2405.14831](https://arxiv.org/abs/2405.14831)
- 2026 survey (Du, arXiv 2603.07670, 8 Mar 2026) frames agent memory as a write–manage–read loop; lists "continual consolidation", "learned forgetting" and "trustworthy reflection" as open problems — [arXiv 2603.07670](https://arxiv.org/abs/2603.07670)

### Inferences
- dore's notes are mostly already "semantic" (single facts), so the CLS split maps to: **episodes** = the raw prompts/sessions a note came from (provenance), **semantic** = merged notes. Keeping episode links lets a later consolidation job re-derive or re-check notes (dore's `recheck` is a first instance of offline replay).
- Roadmap step 4 (project -> general promotion when seen in 2+ projects) is the direct analogue of semanticization: a fact repeated across contexts loses its context and becomes general. Literature supports "keep the episodic copies linked" (hippocampal index), which dore already plans.
- Tse schema result -> a new note that fits an existing cluster (same slot/topic as existing verified notes) can be trusted/merged immediately; a note with no neighbours should stay "episodic"/project-scoped until it recurs.
- Sleep consolidation is selective: the idle-time job should replay a prioritised subset (recent, contradicted, frequently retrieved, high-importance), not the whole DB — consistent with dore's CPU budget rule.
- Reflection that writes new *abstract* notes (Generative Agents) costs LLM tokens and creates agent-written (unverified) facts; under dore's trust rules those must stay `unverified` and never overrule user notes.

### Gaps
- No source quantifies how much LLM-agent "reflection" notes help vs hurt on long horizons; the 2026 survey lists trustworthy reflection as unsolved.
- Did not open McClelland 1995 directly.

---

## 3. Forgetting: Ebbinghaus, decay vs interference, rational forgetting, RIF, why forgetting helps

### Takeaway
Forgetting is adaptive: memory availability tracks the odds that an item will be needed again, which in real environments follows power laws of recency and frequency; forgetting outdated or competing items makes the relevant ones easier to retrieve. A software memory should not delete, but it must make stale or rarely useful notes *less retrievable* (score decay, archive) and actively suppress superseded competitors.

### Cited Findings
- Anderson & Schooler 1991 (Psychol Sci 2:396–408): memory's practice function, retention function, spacing effects and practice × retention interaction mirror the statistics of how often information recurs in the environment (newspaper headlines, child speech, email); memory is an adaptation to need-probability — [Psychological Science page](https://www.psychologicalscience.org/journals/psychological-science/j.1467-9280.1991.tb00174.x/); [PDF](https://dyurovsky.github.io/learning-humans-machines/class/13-class/papers/anderson1991.pdf)
- ⚠️ The specific environmental sources (NYT headlines, CHILDES speech, Anderson's email) and power-law form are from that paper as commonly cited; not re-checked in the PDF this session.
- ACT-R base-level activation B = ln(Σ (t − t_k)^−d), d ≈ 0.5, combines recency and frequency of every past use in one score — [pensyve-core activation.rs](https://docs.rs/crate/pensyve-core/1.0.4/source/src/activation.rs); [TeaParty ACT-R notes](https://dlewissandy.github.io/teaparty/research/act-r/)
- Practitioner advice (blog, unreviewed): use ACT-R decay for "eviction without deletion" and reinforce on *use* not mere retrieval — [dev.to](https://dev.to/futhgar/eviction-without-deletion-running-an-act-r-decay-policy-for-agent-memory-36hi) ⚠️ (blog)
- MemoryBank: Ebbinghaus-style retention R = e^(−t/S); strength S increases each time a memory is recalled, so recalled memories decay slower; old, rarely recalled, low-significance memories are forgotten — [arXiv 2305.10250](https://arxiv.org/abs/2305.10250); [AAAI 2024](https://ojs.aaai.org/index.php/AAAI/article/view/29946)
- Memory Bear (arXiv 2512.20651, Dec 2025) reports combining ACT-R base-level activation with an Ebbinghaus forgetting function; no evaluation results seen — [arXiv 2512.20651](https://arxiv.org/pdf/2512.20651) ⚠️
- Richards & Frankland 2017 (Neuron 94:1071–1084): persistence + transience together optimise memory-guided decisions in changing, noisy environments; forgetting stops overfitting to specific past events and removes outdated info — [PDF copy](https://public.3.basecamp.com/p/8vUmWMnbvEhA5bz7X7qSaEkS/attachments/33022474-9435-11ee-9030-82252566b7e4/download/persistence-transience-memory.pdf); cited in [eLife 63550](https://elifesciences.org/articles/63550)
- Retrieval-induced forgetting (Anderson, Bjork & Bjork 1994, JEP:LMC): retrieving some items lowers later recall of related unpracticed items; dominant account is inhibition of competitors — [Bjork lab PDF](https://bjorklab.psych.ucla.edu/wp-content/uploads/sites/13/2016/07/Anderson_RBjork_EBjork_1994.pdf); contested by a context-based account (Jonker, Seli & MacLeod 2013) — [Psych Rev 2013 PDF](https://uwaterloo.ca/memory-attention-cognition-lab/sites/default/files/uploads/files/psyrev13.pdf)
- Forgetting as adaptive: without forgetting outdated/irrelevant information, remembering relevant information would be very hard (Storm, Bjork & Bjork) — [Storm, Bjork & Bjork 2012 PDF](https://bjorklab.psych.ucla.edu/wp-content/uploads/sites/13/2016/07/Storm_EBjork_Rbjork_2012.pdf)
- ⚠️ Ebbinghaus 1885 savings curve; interference (proactive/retroactive) vs decay debate; Bjork & Bjork 1992 "new theory of disuse" (storage strength vs retrieval strength: items are not lost, only less retrievable) — background, not fetched. The storage/retrieval-strength split is the closest human analogue of "archive, never delete".

### Inferences
- dore's "never hard-delete; archive low-score notes" is aligned with the human picture (storage persists, retrieval strength falls). What is missing per roadmap step 3 is the score: ACT-R base-level activation over *use timestamps* is the best-founded, cheap, no-LLM formula and naturally gives power-law decay + frequency + spacing benefits. MemoryBank's exponential is simpler but Anderson & Schooler's data favour power-law decay.
- "Use" should mean the note was injected **and not contradicted** (or was confirmed), not just retrieved — otherwise hook retrieval noise reinforces junk.
- RIF -> when a correction supersedes a note, the old note should be actively suppressed (marked replaced / `wrong`), not merely out-ranked by recency; dore already does this via replace/merge. Interference is the main cause of the "stale 7/11" problem in the roadmap: reworded updates keep both notes, i.e. two competitors with no inhibition between them.
- Trust and protection should modulate decay (verified user rules decay slowly or not at all), matching "protected notes are never archived automatically".

### Gaps
- No source compares power-law vs exponential decay for LLM agent memory retrieval quality; would need a local benchmark.
- Honda et al. 2025 (HAI) ACT-R + cosine retrieval for LLM agents is cited by a design doc but the paper was not found ⚠️.

---

## 4. Retrieval: cue-dependence, encoding specificity, spreading activation, testing effect, spacing

### Takeaway
Recall depends on the cue matching how the memory was encoded; related memories prime each other; and retrieving a memory (and getting feedback) strengthens it more than re-reading it. A memory system needs multiple retrieval cues per note (the questions it answers, not only its text), associative links, and a "use + feedback" loop that updates strength.

### Cited Findings
- Testing effect: Roediger & Karpicke 2006 (Psychol Sci 17:249–255): restudying beat testing at 5 minutes, but at 2 days and 1 week, students who took a recall test retained more — [PDF](https://psychology.ecu.edu/wp-content/pv-uploads/sites/216/2019/03/Roediger-Karpicke-2006.pdf); Karpicke & Roediger 2008 (Science) on retrieval's critical role in consolidation — [WUSTL profile](https://profiles.wustl.edu/en/publications/the-critical-importance-of-retrieval-for-learning/)
- Spacing: Cepeda et al. 2006 meta-analysis (Psychol Bull 132:354–380), 839 assessments in 317 experiments: spaced beats massed for verbal recall; optimal gap depends on retention interval; effect weaker/absent for some intellectual skills (e.g. math computation) — [PubMed 16719566](https://pubmed.ncbi.nlm.nih.gov/16719566/); [PDF](https://www.evullab.org/pdf/CepedaPashlerVulWixtedRohrer-PB-2006.pdf)
- Generative Agents retrieval = recency (exponential decay on last access) + importance + relevance (embedding cosine), normalised and summed — [Park et al. 2023](https://arxiv.org/pdf/2304.03442). (A secondary source says all weights = 1 in the released code and reports an ablation table; both unverified ⚠️ — [alphaXiv overview](https://www.alphaxiv.org/overview/2304.03442v2))
- Spreading activation in an AI system: HippoRAG's Personalized PageRank over a concept graph spreads activation from query concepts to linked passages — [arXiv 2405.14831](https://arxiv.org/abs/2405.14831)
- ⚠️ Encoding specificity (Tulving & Thomson 1973) and context-dependent memory (Godden & Baddeley 1975, divers recalling better in the environment where they learned); spreading activation (Collins & Loftus 1975) — classic background, not fetched.

### Inferences
- dore's biggest measured retrieval miss ("How long should your answers be?" vs "I prefer short answers") is a textbook **encoding specificity** failure: the cue (a question) does not match the encoded form (a statement). Roadmap step 5's "likely-question keys per note" is the direct fix and is what the human literature predicts would work: store several cues per memory.
- Context cues: project (git root), file path, tool being run are the "environment" of encoding; matching them at retrieval (dore already scopes by project) is the encoding-specificity benefit. Adding the triggering context (e.g. "seen when running pytest") as a key is cheap.
- Testing effect -> a note that is retrieved, shown, and *confirmed by outcome* (user accepts, test passes, no correction follows) should gain strength and possibly trust; this is the roadmap's "user accepting a proposal" signal. Notes never retrieved should not be strengthened by being re-written (re-study is weaker).
- Spacing -> repeated mentions across *different sessions/days* should count more than repeats in one session (massed). dore's "promote repeated habits" should weight distinct days, not raw count.

### Gaps
- No source on optimal number of question-keys per note or their cost; dore measured `bge-base` only.

---

## 5. Updating: reconsolidation, belief revision, source monitoring, metacognition

### Takeaway
Retrieving a memory while something unexpected happens makes it briefly editable (reconsolidation); humans do not tag memories with sources and therefore make source errors; and good learners know what they do not know. A software memory can do better than humans here: keep explicit provenance and trust on every note, update notes only when retrieval meets a mismatch, and report "no memory" or "low confidence" instead of guessing.

### Cited Findings
- Reconsolidation: a brief reminder makes a consolidated memory labile, then it re-stabilises (Nader et al. 2000, as cited) — [PMC7550798](https://pmc.ncbi.nlm.nih.gov/articles/PMC7550798). ⚠️ The original Nature 2000 paper was not opened.
- Prediction error is **necessary** for reconsolidation: propranolol blocked fear-memory reconsolidation only when retrieval included a prediction error (Sevenster, Beckers & Kindt 2013, Science); a single PE triggered it, repeated PEs did not; PE is necessary but not sufficient — [PMC4201815](https://pmc.ncbi.nlm.nih.gov/articles/PMC4201815); [Nat Rev Neurosci highlight](https://www.nature.com/articles/nrn3474)
- Weak PE opens reconsolidation (update the old memory); strong PE shifts to forming a new, competing memory (extinction learning) — [UCL review PDF](https://discovery.ucl.ac.uk/10164630/1/1-s2.0-S0361923023000138-main.pdf)
- Source monitoring (Johnson, Hashtroudi & Lindsay 1993, Psychol Bull 114:3–28): memories carry no explicit source tag; source is inferred from qualitative features through a decision process influenced by goals and metamemory; the same mechanisms produce accurate and false attributions (cryptomnesia, fiction taken as fact) — [doi 10.3758/BF03198562 listing](https://www.doi.org/10.3758/BF03198562); [Mitchell & Johnson 2009 review PDF](https://memlab.yale.edu/sites/default/files/files/2009_Mitchell_Johnson_PsychBull.pdf)
- Metacognition: confidence ratings and the hypercorrection effect show people track how sure they are and learn most from confident errors — [Metcalfe & Finn, PMC3079415](https://pmc.ncbi.nlm.nih.gov/articles/PMC3079415)
- ⚠️ Feeling-of-knowing / Nelson & Narens (1990) monitoring–control framework; AGM belief revision (minimal change) — background, not fetched.

### Inferences
- Reconsolidation maps to: **update notes at retrieval time when the retrieved note mismatches the new message** (same slot, different value). Small mismatch -> edit/replace in place (keep old version linked, never delete). Large mismatch (different context, e.g. different project) -> create a separate note rather than overwrite — mirroring weak vs strong PE. This is a principled rule for dore's "reworded updates keep both notes" problem: if a new note is near an old one and states a different value for the same slot, treat as reconsolidation (replace); if it is merely near, keep both.
- Humans' biggest weakness (no source tags) is a design opportunity: dore's trust levels (`verified`/`unverified`/`wrong`) + origin (user vs agent vs search) + dates are an explicit source-monitoring system. The literature on cryptomnesia/misattribution warns specifically against agent-written text being later treated as user-stated — dore's rule "agent/unverified never overrules a user's verified fact" is exactly the guard.
- Metacognition -> retrieval should return a confidence (score margin, trust, age) and the hook should stay silent when nothing clears the bar (dore's "0 tokens when nothing matches"). Reporting "memory says X (unverified, from 3 months ago)" is better than a bare fact.

### Gaps
- No source on how agent memory systems should calibrate "I don't know" thresholds; the 2026 survey lists trustworthy reflection and contradiction handling but no standard.

---

## 6. Procedural memory / skills vs facts; learning from mistakes and feedback

### Takeaway
Humans keep skills and habits in a separate, non-declarative system learned by repetition and feedback, distinct from facts. AI agents imitate this with skill libraries (verified code/procedures) and verbal lessons from failures; the reliable versions store only procedures that passed a real check.

### Cited Findings
- Memory is multiple systems: declarative (facts, events; conscious) vs nondeclarative (skills, habits, priming; no conscious access), with different anatomy, operating in parallel — [Squire 2004, PubMed 15464402](https://pubmed.ncbi.nlm.nih.gov/15464402/); [Squire & Dede, Conscious and Unconscious Memory Systems](https://doi.org/10.1101/cshperspect.a021667)
- CoALA splits agent memory into working, semantic, episodic and procedural; Voyager stores *verified executable programs* as a skill library refined by execution feedback; Reflexion stores verbal feedback/self-reflections from failed trials and reuses them (episodic) — as described in secondary sources: [Voyager tutorial](https://fareedkhan-dev.github.io/all-agentic-architectures/architectures/29_voyager/), [arXiv 2609.22086](https://arxiv.org/pdf/2609.22086), [arXiv 2610.41143](https://arxiv.org/pdf/2610.41143). ⚠️ Primary papers (Voyager arXiv 2305.16291, Reflexion arXiv 2303.11366, CoALA arXiv 2309.02427) not opened.
- 2026 work flags procedural memory risks: "Procedural Memory Under Change: Reuse and Interference in Controlled Web Tasks" (arXiv 2609.09774) and "Learning by Doing: Autonomously Compiling and Curating Agent Skills from Verified Traces" (arXiv 2611.01386) — titles seen in search only ⚠️, contents unverified: [2609.09774](https://arxiv.org/pdf/2609.09774), [2611.01386](https://arxiv.org/pdf/2611.01386)
- Learning from errors: confident errors + corrective feedback produce strong learning (hypercorrection) — [Butterfield & Metcalfe 2006](https://link.springer.com/article/10.1007/s11409-006-6894-z)

### Inferences
- dore's step-2 result (failed-then-succeeded shell commands gave only junk lessons) is consistent with the human picture: procedural learning needs **many repetitions with a clear outcome signal**, not one noisy episode. Voyager only keeps procedures that passed verification — matching dore's rule "draft-check-fix only with a real checker".
- Keep procedures as a separate note type (how-to, with the check that verified it) from facts; retrieve them by task context (tool/command about to run), not by question similarity.
- The best feedback signal for coding agents is the user's correction of the agent (a confident agent error -> hypercorrection), which dore already learns from the prompt hook.

### Gaps
- No measured evidence found on whether text "lessons" (Reflexion-style) help across *sessions* in real coding use; most results are within-benchmark.

---

## 7. Which human mechanisms are already in AI agent memory designs

### Takeaway
Recency decay, importance scoring, relevance, Ebbinghaus/ACT-R forgetting, reflection-as-consolidation and hippocampal indexing are all implemented in published systems; source monitoring, reconsolidation-on-mismatch, schema-gated fast learning and spacing-aware reinforcement are rarely implemented explicitly.

### Cited Findings
| Human mechanism | AI design | Source |
|---|---|---|
| Recency + importance + relevance | Generative Agents retrieval score; reflection when summed importance > 150 | [arXiv 2304.03442](https://arxiv.org/pdf/2304.03442) |
| Ebbinghaus curve, strengthening on recall | MemoryBank R = e^(−t/S), S grows on recall | [arXiv 2305.10250](https://arxiv.org/abs/2305.10250) |
| ACT-R base-level activation | pensyve-core; Memory Bear (ACT-R + Ebbinghaus) | [docs.rs](https://docs.rs/crate/pensyve-core/1.0.4/source/src/activation.rs); [arXiv 2512.20651](https://arxiv.org/pdf/2512.20651) |
| Hippocampal indexing / spreading activation | HippoRAG KG + Personalized PageRank | [arXiv 2405.14831](https://arxiv.org/abs/2405.14831) |
| CLS replay | DQN experience replay (training-based) | [Kumaran et al. 2016](https://web.stanford.edu/~jlmcc/papers/KumaranHassabisMcClelland16FinalMS.pdf) |
| Procedural memory | Voyager skill library; CoALA taxonomy | secondary: [2609.22086](https://arxiv.org/pdf/2609.22086) |
| Survey framing | write–manage–read loop; open: continual consolidation, learned forgetting, trustworthy reflection | [arXiv 2603.07670](https://arxiv.org/abs/2603.07670) |

- "Cognitive Memory in Large Language Models" (arXiv 2504.02441) surveys MemoryBank and similar systems — [arXiv 2504.02441](https://arxiv.org/pdf/2504.02441) (not opened ⚠️)

### Inferences
- dore already has things most published systems lack: explicit trust/provenance (source monitoring), never-delete with "wrong" kept, newer-wins conflict rule. It lacks what most of them have: a use-based strength/decay score and an offline consolidation pass beyond `recheck`.

### Gaps
- Could not verify Generative Agents' released weights and ablation numbers; did not find head-to-head benchmarks of these cognitive-inspired schemes against plain recency+similarity on LongMemEval/LoCoMo-style tests.

---

## 8. Checklist: human mechanism -> what a non-training memory system must do (with dore status)

### Takeaway
Most of the human toolkit can be imitated with metadata + scoring + an idle-time job; none needs training. dore covers source monitoring, correction-driven updating and never-delete well; the main gaps are a use-based strength score (forgetting/spacing/testing), multi-cue keys (encoding specificity), and slot-level reconsolidation for reworded updates.

### Cited Findings
Status column reflects dore's CLAUDE.md roadmap as of 2026-11-25 (project file, not an external source).

| # | Human mechanism (source) | What the memory system must do | dore today |
|---|---|---|---|
| 1 | Prediction error drives encoding ([PMC6625913](https://pmc.ncbi.nlm.nih.gov/articles/PMC6625913)) | Score new notes by novelty vs existing notes and by contradiction of a stored slot; contradictions get top priority | Partly (corrections handled; no novelty score) |
| 2 | Hypercorrection: confident errors + feedback learned best ([Butterfield & Metcalfe 2006](https://link.springer.com/article/10.1007/s11409-006-6894-z)) | Treat user corrections of the agent as the strongest learning event; store as `verified`, demote the wrong note to `wrong` | Yes |
| 3 | CLS: fast episodic + slow semantic ([Kumaran 2016](https://web.stanford.edu/~jlmcc/papers/KumaranHassabisMcClelland16FinalMS.pdf)) | Keep raw episodes (source prompt/session ids) linked to each distilled note; distil gradually | Partly (dates/notes; episode links unclear) |
| 4 | Selective offline replay in sleep ([Rasch & Born](https://pmc.ncbi.nlm.nih.gov/articles/3768102)) | Idle-time low-priority job that replays a *prioritised* subset: merge duplicates, re-check against current rules, resolve conflicts | Started (`recheck`); merge/score left (step 3) |
| 5 | Schema-fit speeds consolidation ([Tse 2007](https://pubmed.ncbi.nlm.nih.gov/17412951/)) | New note that fits an existing cluster/slot can merge at once; isolated notes stay project-scoped until they recur | Not explicit |
| 6 | Semanticization across contexts (CLS) | Fact seen in 2+ projects/contexts -> general note, project copies kept and linked; project-specific names never go general | Planned (step 4) |
| 7 | Rational forgetting tracks need-probability ([Anderson & Schooler 1991](https://www.psychologicalscience.org/journals/psychological-science/j.1467-9280.1991.tb00174.x/)) | Strength = ACT-R-style ln Σ (t−t_k)^−0.5 over *useful-use* timestamps, weighted by trust; archive below threshold; never delete | Planned (step 3) |
| 8 | Storage vs retrieval strength (⚠️ Bjork & Bjork 1992) | Archived notes remain searchable on explicit request and can be revived when cued again | Archive exists; revival unclear |
| 9 | Retrieval-induced forgetting / interference ([Anderson et al. 1994](https://bjorklab.psych.ucla.edu/wp-content/uploads/sites/13/2016/07/Anderson_RBjork_EBjork_1994.pdf)) | When a note wins a slot, actively suppress its superseded competitors (don't rely on recency ranking alone) | Partly; reworded updates still keep both (stale 7/11) |
| 10 | Encoding specificity (⚠️ Tulving & Thomson 1973) | Multiple cues per note: likely questions, slot name, context (project, tool, file) | Planned (step 5) |
| 11 | Spreading activation ([HippoRAG](https://arxiv.org/abs/2405.14831)) | Links between notes (same entity/slot/project) so one hit can pull related notes; cap fan-out for token cost | Not yet |
| 12 | Testing effect ([Roediger & Karpicke 2006](https://psychology.ecu.edu/wp-content/pv-uploads/sites/216/2019/03/Roediger-Karpicke-2006.pdf)) | Strengthen a note when it was shown *and* the outcome confirmed it (user accepted, no correction); not on mere retrieval | Implicit feedback exists; "accepted proposal" signal next |
| 13 | Spacing effect ([Cepeda 2006](https://pubmed.ncbi.nlm.nih.gov/16719566/)) | Count repeats across distinct days/sessions more than repeats within one session when promoting or protecting | Not explicit |
| 14 | Reconsolidation needs prediction error ([Sevenster, PMC4201815](https://pmc.ncbi.nlm.nih.gov/articles/PMC4201815)) | Only edit a note when retrieval meets a mismatch; small mismatch -> replace (keep old version), large mismatch/different context -> new separate note | Newer-wins replace exists; slot-level matching is the gap |
| 15 | Source monitoring ([Johnson et al. 1993](https://www.doi.org/10.3758/BF03198562)) | Store origin (user / agent / search / file), date, trust on every note; agent text never becomes user fact | Yes (trust levels, rules) |
| 16 | Metacognition ([Metcalfe & Finn](https://pmc.ncbi.nlm.nih.gov/articles/PMC3079415)) | Return confidence; stay silent below threshold; label unverified/old notes when shown | Partly (silent when no match) |
| 17 | Procedural vs declarative ([Squire 2004](https://pubmed.ncbi.nlm.nih.gov/15464402/)) | Separate how-to notes, kept only after a real check passes; retrieve by task context | Not adopted (step 2 measured junk) |
| 18 | Persistence + transience balance ([Richards & Frankland 2017](https://public.3.basecamp.com/p/8vUmWMnbvEhA5bz7X7qSaEkS/attachments/33022474-9435-11ee-9030-82252566b7e4/download/persistence-transience-memory.pdf)) | Measure both: stale/leak mistakes (too much persistence) and lost facts (too much transience) | Yes (`bench stream` stale/leak/junk) |

### Inferences
- Highest-leverage next steps implied by the literature, in dore's one-step-at-a-time order: (a) use-based ACT-R strength for step 3 (forgetting, spacing, testing effect all fall out of one formula); (b) slot-level mismatch detection for reconsolidation/RIF, which targets the measured stale 7/11; (c) question keys for step 5 (encoding specificity).
- Human memory's main failure modes (source misattribution, false memory from rehearsing fiction, interference) argue for keeping dore's strict trust rules even when they cost recall.

### Gaps
- Status column is inferred from the project's CLAUDE.md roadmap, not from reading the code.
- No external evidence on which of these mechanisms gives the biggest gain for coding-agent memory specifically; that needs `bench stream` measurements.
