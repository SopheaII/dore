<h1 align="center">dore</h1>

<p align="center">
  <strong>Memory for Claude Code. Say it once, it remembers in every new session.</strong><br/>
  Runs on your laptop · your notes never leave your machine · learns with Claude Haiku between sessions
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

Claude Code forgets everything between sessions, so you explain the same things again and again. dore fixes that:

- 👂 **It listens.** Tell Claude a fact ("our staging server uses port 8443") — no "remember this" needed.
- 💡 **It reminds.** Ask about it later, even in a new session, and dore puts that note in front of Claude first.
- 🔄 **It updates.** A new value ("the port is now 9443") replaces the old one.
- 🗂️ **It keeps things in place.** Facts about you follow you into every project; facts about one project stay there.

## How is it different from other memory tools?

Most memory tools let the AI decide what to save, then load it into every message: you pay tokens, and a fact is
lost when the AI forgets to save it. **dore saves outside the model** (~13 ms, **0 Claude tokens**) and gives Claude
only the notes that match your message.

| | Usual memory tools | dore |
|---|---|---|
| Who decides what to save | The AI (costs tokens, can forget) | Local rules at once, Haiku between sessions |
| What Claude receives | Everything, or what the AI searched | Only matching notes (plus rules once a session) |
| Conflicting notes | Old and new may both stay | New beats old; you beat the AI |
| Where facts belong | No rule | You vs. project, kept apart |
| Where it runs | Sometimes a cloud service | On your computer; notes stay local |

At a session end, Haiku sorts what you typed (not Claude's replies) into facts, rules and noise, in one batch: about
6k tokens a day (estimate), never while you work.

## See it work in Claude Code

Left: **without** dore. Right: **with** dore. Real Claude Code sessions, recorded in a terminal.

**Same project:** tell Claude a fact, close it, start a new session, and ask.

![Same project: without dore Claude can't find the port; with dore it answers 8443](docs/images/claude-code-same-project.gif)

### Shared across projects

Facts about you are shared by all your projects. Tell it in project **api**, then ask in project **shop**:

![Different project: without dore Claude can't tell; with dore it answers Go](docs/images/claude-code-other-project.gif)

Facts about one project (like its port) stay in that project.

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

![How dore works: learn, recall, update, rules like habits, Haiku review](docs/images/how-it-works.svg)

- **Learn:** dore reads each message before Claude does and keeps facts and rules. It skips questions and requests.
- **Recall:** it adds only the notes that match your message. Nothing matches, nothing is added.
- **Update:** a new value replaces the old one. The old note is hidden but kept, so the old value never comes back.
- **Rules like habits:** a rule you repeat or Claude follows gets stronger and starts each session; unused ones fade.
- **Haiku review:** at a session end, Haiku checks what you typed and pasted (not Claude's replies)
  and keeps or merges notes, deleting the junk; a pasted list is kept whole, a log or error is dropped. Until it runs (or
  when `claude` can't be reached), local word rules keep what you say.

## Privacy

- **Stays on your machine:** every note, everything you type, your projects and the search model's work.
  dore has no account, no server and no telemetry.
- **Haiku learning:** at a session end,
  what you typed since the last batch, and the start and end of anything long you pasted (code and logs included),
  go to Claude Haiku through your own `claude` login, like any message you send Claude. Your notes stay on your
  machine.
- **Besides Haiku, the only thing dore sends:** once a day, one request for the public page
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
