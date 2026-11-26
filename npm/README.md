<h1 align="center">dore</h1>

<p align="center">
  <strong>Memory for Claude Code. Say it once, it remembers in every new session.</strong><br/>
  Runs on your laptop · free to learn · nothing leaves your machine
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Claude_Code-plugin_0.5.1-d97757?style=flat-square" alt="Claude Code plugin 0.5.1" />
  <a href="https://www.npmjs.com/package/dore-memory"><img src="https://img.shields.io/npm/v/dore-memory?style=flat-square&logo=npm" alt="npm" /></a>
  <img src="https://img.shields.io/badge/python-3.11+-3776ab?style=flat-square&logo=python&logoColor=white" alt="Python 3.11+" />
  <img src="https://img.shields.io/badge/data-stays_local-2ea44f?style=flat-square" alt="Data stays local" />
  <img src="https://img.shields.io/badge/license-MIT-blue?style=flat-square" alt="MIT license" />
</p>

## Why dore

**Problem:** every new Claude Code session forgets what you told it, so you repeat yourself.

**Solution:** dore remembers what you say, just by talking as usual.

- 🪶 **Saves tokens:** learning costs 0 Claude tokens; most prompts get nothing added.
- 🧠 **Learns over time:** newer facts replace older ones, with no model training.
- 🗂️ **Shared across projects:** facts about you go everywhere; project facts stay put.
- ⚡ **Fast and private:** about 13 ms per prompt; everything stays on your machine.

## See it work in Claude Code

Real screenshots: two Claude Code windows side by side, left **without** dore, right **with** dore.
Claude Code's own memory is turned off on both sides, so only dore can remember.

**Session 1:** tell Claude a fact.

![Session 1: both sides are told the staging port](https://raw.githubusercontent.com/SopheaII/dore-memory/master/docs/images/claude-code-1-tell.png)

**Session 2:** close Claude, start a new session, and ask.

![Session 2: without dore Claude can't find it; with dore it answers 8443](https://raw.githubusercontent.com/SopheaII/dore-memory/master/docs/images/claude-code-2-ask.png)

Without dore, Claude can't find the port. With dore, it answers **8443** right away.

### Shared across projects

Facts about you are shared by all your projects. Tell it in project **api**:

![Project api: both sides are told "I write all my APIs in Go"](https://raw.githubusercontent.com/SopheaII/dore-memory/master/docs/images/claude-code-3-other-project-tell.png)

Then ask in a different project, **shop**:

![Project shop: without dore Claude can't tell; with dore it answers Go](https://raw.githubusercontent.com/SopheaII/dore-memory/master/docs/images/claude-code-4-other-project-ask.png)

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

Needs Node 18+, [Claude Code](https://claude.com/claude-code), and [uv](https://docs.astral.sh/uv/) or Python 3.11+.

```bash
npx dore-memory install     # set up dore + the Claude Code plugin
npx dore-memory status      # check it
npx dore-memory update      # get the latest version
npx dore-memory uninstall   # remove it (your memory is kept)
```

dore lives in `~/.dore-memory` (change it with `DORE_HOME`).

### From source

```bash
git clone https://github.com/SopheaII/dore-memory.git ~/Documents/dore
cd ~/Documents/dore                     # or set DORE_HOME to where it is
uv venv .venv --python 3.12
uv pip install --python .venv/bin/python -e ".[dev]"
claude plugin marketplace add ~/Documents/dore
claude plugin install dore-memory@dore-memory
```

Then use Claude Code as usual. Works on macOS and Linux, no GPU. It also works with opencode and other MCP agents.

## Limits

- One question per fact works best. If one question asks two things, it may answer only one.
- Different words for the same thing ("job" vs "work as a nurse") may not match.
- English only.

## More

[`AGENTS.md`](https://github.com/SopheaII/dore-memory/blob/master/AGENTS.md) (design and roadmap) · [`.agents/rules/`](https://github.com/SopheaII/dore-memory/blob/master/.agents/rules) (details and all measurements) ·
[`REFERENCES.md`](https://github.com/SopheaII/dore-memory/blob/master/REFERENCES.md) (where the ideas come from)

## License

[MIT](https://github.com/SopheaII/dore-memory/blob/master/LICENSE): free to use, change and share.
