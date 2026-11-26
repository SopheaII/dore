<h1 align="center">dore</h1>

<p align="center">
  <strong>Memory for Claude Code. Say it once, it remembers in every new session.</strong><br/>
  Runs on your laptop · your notes never leave your machine · optional Haiku learning, about once a day
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Claude_Code-plugin_0.6.1-d97757?style=flat-square" alt="Claude Code plugin 0.6.1" />
  <a href="https://github.com/SopheaII/dore-memory/actions/workflows/ci.yml"><img src="https://img.shields.io/github/actions/workflow/status/SopheaII/dore-memory/ci.yml?branch=master&style=flat-square&label=CI" alt="CI" /></a>
  <a href="https://www.npmjs.com/package/dore-memory"><img src="https://img.shields.io/npm/v/dore-memory?style=flat-square&logo=npm" alt="npm" /></a>
  <img src="https://img.shields.io/badge/python-3.11+-3776ab?style=flat-square&logo=python&logoColor=white" alt="Python 3.11+" />
  <img src="https://img.shields.io/badge/memory-stays_local-2ea44f?style=flat-square" alt="Memory stays local" />
  <img src="https://img.shields.io/badge/license-MIT-blue?style=flat-square" alt="MIT license" />
</p>

```bash
npx dore-memory install     # sets up dore and its Claude Code plugin, then open a new Claude Code session
```

## Why dore

**Problem:** Claude Code forgets everything when you start a new session, so you explain the same things again and again.

**Solution:** dore gives Claude a memory that works like yours:

- 👂 **It listens.** When you tell Claude a fact ("our staging server uses port 8443"), dore saves it.
  You don't need to say "remember this".
- 💡 **It reminds.** When you ask about it later, even in a new session, dore hands Claude that note before it answers.
- 🔄 **It updates.** When a fact changes ("the staging port is now 9443"), the new fact replaces the old one.
- 🗂️ **It keeps things in place.** Facts about you (your name, how you like to work) are used in every project.
  Facts about one project (its port, its database) stay in that project.

## How is it different from other memory tools?

Most memory tools let the AI manage the memory: the AI decides what to save, and then either loads the whole
memory into every message or has to search it. That costs tokens, and if the AI forgets to save, the fact is lost.

dore manages the memory itself, outside the AI:

| | Usual memory tools | dore |
|---|---|---|
| Who decides what to save | The AI (costs tokens, and it can forget) | dore, from what you type: local rules (free), or, if you turn it on, Haiku in one small batch a day |
| What Claude receives | The whole memory, or what the AI searched for | Only the notes that match your message (usually none), plus your standing rules once per session |
| When a fact changes | Old and new notes may both stay | The old note is replaced |
| When notes disagree | No rule | What you said wins over what the AI guessed |
| Where it runs | Sometimes a cloud service | On your computer (with Haiku learning on, the sentences you type also go to Haiku once a day) |

Learning adds a few ms to each message. By default it costs 0 Claude tokens (local word rules). If you say yes at
install, dore learns better with Claude Haiku instead: about once a day, in the background, one small batch
(about 5-10k Haiku tokens a day on real use) sorts what you typed into facts, rules and noise.

## See it work in Claude Code

Left: **without** dore. Right: **with** dore.

**Session 1:** tell Claude a fact.

![Session 1: both sides are told the staging port](docs/images/claude-code-1-tell.png)

**Session 2:** close Claude, start a new session, and ask.

![Session 2: without dore Claude can't find it; with dore it answers 8443](docs/images/claude-code-2-ask.png)

Without dore, Claude can't find the port. With dore, it answers **8443** right away.

### Shared across projects

Facts about you are shared by all your projects. Tell it in project **api**:

![Project api: both sides are told "I write all my APIs in Go"](docs/images/claude-code-3-other-project-tell.png)

Then ask in a different project, **shop**:

![Project shop: without dore Claude can't tell; with dore it answers Go](docs/images/claude-code-4-other-project-ask.png)

Without dore, Claude can't tell. With dore, it knows: **Go**. Facts about one project (like its port) stay in
that project.

## Test results

| Test | Result |
|---|---|
| Remembers facts across 20 sessions | **80 of 80** |
| Shows an outdated value after a change | **0 of 53** |
| Saves chatter (requests, questions) by mistake | **0 of 39** |
| Correct after 24 weeks, 12 projects | **81%** |
| Time per prompt | **13 ms** |

Run them yourself (no AI model needed, a few seconds each):

```bash
.venv/bin/pytest -q
.venv/bin/python -m dore.eval.conversation
.venv/bin/python -m dore.eval.learning
```

## Install

### With npm (recommended)

Needs Node 18+, [Claude Code](https://claude.com/claude-code), and [uv](https://docs.astral.sh/uv/) or Python 3.11+.

```bash
npx dore-memory install
```

Then start a new Claude Code session and talk as usual. That's it.

| Command | What it does |
|---|---|
| `npx dore-memory install` | Sets up dore and turns on its Claude Code plugin |
| `npx dore-memory status` | Shows where dore is and whether the plugin is on |
| `npx dore-memory@latest update` | Gets the latest dore and its plugin |
| `npx dore-memory uninstall` | Removes dore and the plugin (your memory is kept) |

**What `install` does:** sets up dore in `~/.dore-memory` and turns on its Claude Code plugin.
Your memory is saved in `~/.dore-memory/data`. Change the folder with `DORE_HOME`.
The first install downloads about 200 MB (Python packages and a small search model).

**Updates are automatic.** Once a day, while you are not typing, dore asks npm whether a newer version is
out and, if so, updates itself in the background at low priority (no message; log in `~/.dore-memory/data/update.log`).
Turn this off with `DORE_NO_AUTO_UPDATE=1` (`NO_UPDATE_NOTIFIER=1`, `DO_NOT_TRACK=1` and Claude Code's
`DISABLE_AUTOUPDATER=1` also turn it off), then update by hand with `npx dore-memory@latest update`.
Installs from source never update by themselves.

### From source

```bash
git clone https://github.com/SopheaII/dore-memory.git ~/Documents/dore
cd ~/Documents/dore                     # or set DORE_HOME to where it is
uv venv .venv --python 3.12
uv pip install --python .venv/bin/python -e ".[dev]"
claude plugin marketplace add ~/Documents/dore
claude plugin install dore-memory@dore-memory
```

Works on macOS, Linux and Windows (Claude Code on Windows uses Git Bash, which dore's hooks need), no GPU.
It also works with opencode and other MCP agents.

## How it works

1. **You type a message** in Claude Code. dore's hook reads it before Claude does.
2. **If it tells a fact** ("our staging port is 8443"), dore saves it as a note on your machine.
   Questions and requests are not saved.
3. **If it asks about something dore knows**, the hook adds the matching notes (a few lines) to your
   message, so Claude can answer. If nothing matches, nothing is added (0 tokens).
4. **If a fact changes** ("the port is now 9443"), the newer note replaces the old one.
5. **Rules you repeat** ("never use tabs", said in two sessions, in any words) or that Claude keeps following start
   each new session, in a few lines at most; rules you stop repeating fade, like habits, and still come back when a
   message matches them.

With Haiku learning on, steps 2 and 4 happen later: every sentence you type is kept on your machine at once, and
about once a day dore's background helper sends the waiting ones (not code, logs, pastes or Claude's replies) to
Haiku through your own `claude` command. Haiku says which are lasting facts or rules, which repeat or update an
existing note, and which are noise. Nothing is deleted; an old note is hidden only when a second check agrees
it is out of date. Offline or at your plan's limit, the sentences wait and are tried again later.

Without Haiku, learning runs locally with small models: no Claude tokens, and your memory never leaves your machine.

## Privacy

- **Stays on your machine:** every note, everything you type, your projects and the search model's work.
  dore has no account, no server and no telemetry.
- **With Haiku learning on** (you choose at install; change it in `~/.dore-memory/data/learner`): about once a day,
  the sentences you typed since the last time go to Claude Haiku through your own `claude` login, like any message
  you send Claude. Your notes stay on your machine.
- **Otherwise the only thing dore sends:** once a day, one request for the public page
  `https://registry.npmjs.org/dore-memory/latest` to see the newest version number. It carries nothing about
  you or your memory; npm sees an ordinary request from your IP address. When there is a newer version, the
  update downloads it from npm and GitHub. Off with `DORE_NO_AUTO_UPDATE=1`.
- Installing and updating download packages from npm, GitHub and PyPI, like any installer.

## Limits

- One question per fact works best. If one question asks two things, it may answer only one.
- Different words for the same thing ("job" vs "work as a nurse") may not match.
- English only.

## More

[`AGENTS.md`](AGENTS.md) (design and roadmap) · [`.agents/rules/`](.agents/rules) (details and all measurements) ·
[`REFERENCES.md`](REFERENCES.md) (where the ideas come from)

## License

[MIT](LICENSE): free to use, change and share.
