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
const HOME = process.env.DORE_HOME || path.join(os.homedir(), ".dore-memory");
const VENV = path.join(HOME, ".venv");
const HOOK = path.join(VENV, "bin", "dore-hook");
const DATA = process.env.DORE_DATA || path.join(HOME, "data");
// Until dore-memory is on PyPI, install from GitHub. Override with DORE_PIP_SPEC (e.g. "dore-memory").
const SPEC = process.env.DORE_PIP_SPEC || `git+https://github.com/${REPO}.git`;

const say = (msg) => console.log(`dore-memory: ${msg}`);
const fail = (msg) => { console.error(`dore-memory: ${msg}`); process.exit(1); };

function has(cmd) {
  return spawnSync("sh", ["-c", `command -v ${cmd}`], { stdio: "ignore" }).status === 0;
}

function run(cmd, args, { allowFail = false } = {}) {
  console.log(`  $ ${[cmd, ...args].join(" ")}`);
  const r = spawnSync(cmd, args, { stdio: "inherit" });
  if (r.status !== 0 && !allowFail) fail(`command failed: ${cmd} ${args.join(" ")}`);
  return r.status === 0;
}

function pythonOk(py) {
  const r = spawnSync(py, ["-c", "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)"]);
  return r.status === 0;
}

function installPython(upgrade) {
  fs.mkdirSync(HOME, { recursive: true });
  if (has("uv")) {
    if (!fs.existsSync(VENV)) run("uv", ["venv", VENV, "--python", "3.12"]);
    run("uv", ["pip", "install", "--python", path.join(VENV, "bin", "python"), ...(upgrade ? ["--upgrade"] : []), SPEC]);
  } else {
    const py = ["python3.12", "python3.11", "python3.13", "python3"].find((p) => has(p) && pythonOk(p));
    if (!py) fail("needs Python 3.11+ or uv. Install uv: curl -LsSf https://astral.sh/uv/install.sh | sh");
    if (!fs.existsSync(VENV)) run(py, ["-m", "venv", VENV]);
    const pip = path.join(VENV, "bin", "pip");
    run(pip, ["install", "--quiet", "--upgrade", "pip"]);
    run(pip, ["install", ...(upgrade ? ["--upgrade"] : []), SPEC]);
  }
  if (!fs.existsSync(HOOK)) fail(`install finished but ${HOOK} is missing`);
}

function installPlugin() {
  if (!has("claude")) {
    say("Claude Code CLI not found. Install Claude Code, then run: npx dore-memory install");
    return false;
  }
  // "add" fails when the marketplace is already known; that is fine.
  run("claude", ["plugin", "marketplace", "add", REPO], { allowFail: true });
  run("claude", ["plugin", "marketplace", "update", "dore-memory"], { allowFail: true });
  return run("claude", ["plugin", "install", PLUGIN], { allowFail: true });
}

function install(upgrade) {
  if (process.platform === "win32") fail("Windows is not supported yet (macOS and Linux only).");
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
  if (fs.existsSync(VENV)) fs.rmSync(VENV, { recursive: true, force: true });
  say("removed the plugin and the Python environment.");
  // dore never deletes memories: the notes stay unless the user removes them.
  console.log(`  Your memory was kept in ${DATA}. Delete that folder yourself if you want it gone.`);
}

function status() {
  console.log(`home:    ${HOME}`);
  console.log(`hook:    ${fs.existsSync(HOOK) ? HOOK : "missing (run: npx dore-memory install)"}`);
  console.log(`memory:  ${fs.existsSync(path.join(DATA, "memory.db")) ? path.join(DATA, "memory.db") : "empty"}`);
  if (has("claude")) {
    const r = spawnSync("claude", ["plugin", "list"], { encoding: "utf8" });
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

Environment: DORE_HOME (default ~/.dore-memory), DORE_PIP_SPEC (what to pip install).`;

const cmd = process.argv[2];
if (cmd === "install") install(false);
else if (cmd === "update") { installPython(true); installPlugin(); say("updated."); }
else if (cmd === "status") status();
else if (cmd === "uninstall") uninstall();
else { console.log(HELP); process.exit(cmd && !["-h", "--help", "help"].includes(cmd) ? 1 : 0); }
