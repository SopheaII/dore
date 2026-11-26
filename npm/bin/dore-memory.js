#!/usr/bin/env node
// Installer for dore (local long-term memory for Claude Code).
// dore itself is Python: this sets it up in ~/.dore-memory (or $DORE_HOME) and registers the
// Claude Code plugin, whose hooks run ~/.dore-memory/.venv/bin/dore-hook. No dependencies.
"use strict";

const { spawnSync } = require("node:child_process");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");

const REPO = "SopheaII/dore-memory";
const PLUGIN = "dore-memory@dore-memory";
const IS_WIN = process.platform === "win32";
const EXE = IS_WIN ? ".exe" : "";
const HOME = process.env.DORE_HOME || path.join(os.homedir(), ".dore-memory");
const VENV = path.join(HOME, ".venv");
const VENV_BIN = path.join(VENV, IS_WIN ? "Scripts" : "bin"); // Windows venvs keep programs in Scripts\
const VENV_PY = path.join(VENV_BIN, "python" + EXE);
const HOOK = path.join(VENV_BIN, "dore-hook" + EXE);
const DATA = process.env.DORE_DATA || path.join(HOME, "data");
// Until dore-memory is on PyPI, install from GitHub. Override with DORE_PIP_SPEC (e.g. "dore-memory").
const SPEC = process.env.DORE_PIP_SPEC || `git+https://github.com/${REPO}.git`;
// Where the Claude Code plugin comes from; a local folder (a dore checkout) works too, for testing.
const MARKET = process.env.DORE_MARKETPLACE || REPO;

const say = (msg) => console.log(`dore-memory: ${msg}`);
const fail = (msg) => { console.error(`dore-memory: ${msg}`); process.exit(1); };

function has(cmd) {
  if (IS_WIN) return spawnSync("where", [cmd], { stdio: "ignore" }).status === 0;
  return spawnSync("sh", ["-c", `command -v ${cmd}`], { stdio: "ignore" }).status === 0;
}

// Windows: `claude` and `npm` are often .cmd files, which only start through the shell;
// quote arguments there so paths with spaces (C:\Users\First Last) stay whole.
function spawn(cmd, args, opts) {
  if (!IS_WIN) return spawnSync(cmd, args, opts);
  const q = (a) => (/[\s"]/.test(a) ? `"${a.replace(/"/g, '\\"')}"` : a);
  return spawnSync([cmd, ...args].map(q).join(" "), { ...opts, shell: true });
}

function run(cmd, args, { allowFail = false, env } = {}) {
  console.log(`  $ ${[cmd, ...args].join(" ")}`);
  const r = spawn(cmd, args, { stdio: "inherit", ...(env ? { env } : {}) });
  if (r.status !== 0 && !allowFail) fail(`command failed: ${cmd} ${args.join(" ")}`);
  return r.status === 0;
}

function pythonOk(py) {
  const r = spawnSync(py, ["-c", "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)"]);
  return r.status === 0;
}

function ask(question) {
  // No terminal (CI, piped, run by an agent): go ahead, like other installers do.
  if (!process.stdin.isTTY) return true;
  process.stdout.write(`${question} [Y/n] `);
  const buf = Buffer.alloc(256);
  let answer = "";
  try { answer = buf.toString("utf8", 0, fs.readSync(0, buf, 0, 256, null)).trim().toLowerCase(); } catch {}
  return answer === "" || answer.startsWith("y");
}

// uv's own installer puts it in ~/.local/bin (or $XDG_BIN_HOME, $CARGO_HOME/bin); same on Windows.
function findUv() {
  if (has("uv")) return "uv";
  const dirs = [process.env.XDG_BIN_HOME, path.join(os.homedir(), ".local", "bin"),
    path.join(process.env.CARGO_HOME || path.join(os.homedir(), ".cargo"), "bin")];
  return dirs.filter(Boolean).map((d) => path.join(d, "uv" + EXE)).find((p) => fs.existsSync(p)) || null;
}

function installUv() {
  say("dore needs Python 3.11+. uv (https://docs.astral.sh/uv/) can set it up for dore only.");
  if (!ask("Install uv now?")) fail("stopped. Install Python 3.11+ or uv, then run: npx dore-memory install");
  if (IS_WIN) {
    // Started from PowerShell 7, Windows PowerShell 5 inherits 7's PSModulePath and fails to load its
    // own modules ("module could not be loaded"); give it a clean one. Fall back to pwsh if needed.
    const env = Object.fromEntries(Object.entries(process.env).filter(([k]) => k.toLowerCase() !== "psmodulepath"));
    const ps = ["-NoProfile", "-ExecutionPolicy", "ByPass", "-Command", "irm https://astral.sh/uv/install.ps1 | iex"];
    const ok = run("powershell", ps, { env, allowFail: true }) || (has("pwsh") && run("pwsh", ps, { allowFail: true }));
    if (!ok) fail("could not install uv. Install it yourself (https://docs.astral.sh/uv/), then run: npx dore-memory install");
  } else {
    if (!has("curl")) fail("needs curl to install uv. Install uv yourself: https://docs.astral.sh/uv/");
    run("sh", ["-c", "curl -LsSf https://astral.sh/uv/install.sh | sh"]);
  }
  return findUv() || fail("uv was installed but not found. Open a new terminal and run: npx dore-memory install");
}

function installPython(upgrade) {
  fs.mkdirSync(HOME, { recursive: true });
  // Windows: always uv ("python" there is often the Microsoft Store placeholder).
  const py = IS_WIN ? null : ["python3.12", "python3.11", "python3.13", "python3"].find((p) => has(p) && pythonOk(p));
  // Prefer uv (it downloads Python 3.12 by itself); else a Python 3.11+ already here; else install uv.
  const uv = findUv() || (py ? null : installUv());
  if (uv) {
    // Windows on ARM: spaCy has no win_arm64 package, so use x64 Python (Windows runs it emulated).
    const pyWant = IS_WIN && os.arch() === "arm64" ? "cpython-3.12-windows-x86_64-none" : "3.12";
    if (!fs.existsSync(VENV)) run(uv, ["venv", VENV, "--python", pyWant]);
    run(uv, ["pip", "install", "--python", VENV_PY, ...(upgrade ? ["--upgrade"] : []), SPEC]);
  } else {
    if (!fs.existsSync(VENV)) run(py, ["-m", "venv", VENV]);
    const pip = path.join(VENV_BIN, "pip");
    run(pip, ["install", "--quiet", "--upgrade", "pip"]);
    run(pip, ["install", ...(upgrade ? ["--upgrade"] : []), SPEC]);
  }
  if (!fs.existsSync(HOOK)) fail(`install finished but ${HOOK} is missing`);
  warmUp();
}

// The first hook run downloads the search model (~130 MB). That takes longer than Claude Code
// waits for a hook (20 s), so the user's first message would be lost. Do it here instead.
function warmUp() {
  say("downloading the search model and opening the memory (one time, about 30 s)...");
  const code = "from dore.config import Config\nfrom dore.integrations.hooks import open_store\n"
    + "from dore.learn.grammar import nlp\nopen_store(Config()).close()\nnlp()\n";
  const r = spawnSync(VENV_PY, ["-c", code], {
    stdio: ["ignore", "ignore", "inherit"],
    env: { ...process.env, DORE_HOME: HOME, HF_HUB_DISABLE_PROGRESS_BARS: "1" },
  });
  if (r.status !== 0) fail("could not download the search model. Check your internet connection and run install again.");
}

function installPlugin() {
  if (!has("claude")) {
    say("Claude Code CLI not found. Install Claude Code, then run: npx dore-memory install");
    return false;
  }
  // "add" fails when the marketplace is already known; that is fine.
  run("claude", ["plugin", "marketplace", "add", MARKET], { allowFail: true });
  run("claude", ["plugin", "marketplace", "update", "dore-memory"], { allowFail: true });
  return run("claude", ["plugin", "install", PLUGIN], { allowFail: true });
}

function install(upgrade) {
  say(`setting up in ${HOME} (first run downloads ~200 MB of packages and models)`);
  installPython(upgrade);
  const plugin = installPlugin();
  say("done.");
  console.log(`  memory:  ${DATA}`);
  console.log(`  plugin:  ${plugin ? PLUGIN + " installed" : "not installed (see above)"}`);
  console.log("  Start a new Claude Code session; dore learns from what you tell it.");
}

function uninstall() {
  if (has("claude")) run("claude", ["plugin", "uninstall", PLUGIN], { allowFail: true });
  // Stop dore's background helper first: Windows can't delete files a running program uses.
  if (fs.existsSync(HOOK)) spawnSync(HOOK, ["quit"], { stdio: "ignore", timeout: 10000 });
  try {
    if (fs.existsSync(VENV)) fs.rmSync(VENV, { recursive: true, force: true, maxRetries: 5, retryDelay: 500 });
  } catch {
    // Windows keeps files of a running program locked; dore's helper quits by itself after 30 idle minutes.
    fail(`could not remove ${VENV} (dore's helper may still be running). Close Claude Code, wait a minute, and run uninstall again.`);
  }
  say("removed the plugin and the Python environment.");
  // dore never deletes memories: the notes stay unless the user removes them.
  console.log(`  Your memory was kept in ${DATA}. Delete that folder yourself if you want it gone.`);
}

function status() {
  console.log(`home:    ${HOME}`);
  console.log(`hook:    ${fs.existsSync(HOOK) ? HOOK : "missing (run: npx dore-memory install)"}`);
  console.log(`memory:  ${fs.existsSync(path.join(DATA, "memory.db")) ? path.join(DATA, "memory.db") : "empty"}`);
  if (has("claude")) {
    const r = spawn("claude", ["plugin", "list"], { encoding: "utf8" });
    const on = (r.stdout || "").includes(PLUGIN);
    console.log(`plugin:  ${on ? PLUGIN : "not installed"}`);
  } else {
    console.log("plugin:  Claude Code CLI not found");
  }
}

const HELP = `Usage: npx dore-memory <command>

  install     set up dore and its Claude Code plugin
  update      upgrade dore to the latest version
  status      show where dore is and whether the plugin is on
  uninstall   remove the plugin and Python environment (keeps your memory)

Environment: DORE_HOME (default ~/.dore-memory), DORE_PIP_SPEC (what to pip install),
DORE_MARKETPLACE (where the plugin comes from; default the GitHub repo).`;

const cmd = process.argv[2];
if (cmd === "install") install(false);
else if (cmd === "update") { installPython(true); installPlugin(); say("updated."); }
else if (cmd === "status") status();
else if (cmd === "uninstall") uninstall();
else { console.log(HELP); process.exit(cmd && !["-h", "--help", "help"].includes(cmd) ? 1 : 0); }
