// Runs before `npm pack` / `npm publish`: copies the repo README into the npm package so the
// npm page matches GitHub. Relative links and images become absolute GitHub URLs.
"use strict";
const fs = require("node:fs");
const path = require("node:path");

const BLOB = "https://github.com/SopheaII/dore-memory/blob/master/";
const RAW = "https://raw.githubusercontent.com/SopheaII/dore-memory/master/";
const isRelative = (url) => !/^(https?:|mailto:|#)/.test(url);

let s = fs.readFileSync(path.join(__dirname, "..", "..", "README.md"), "utf8");
// Images first: ![alt](path) -> raw file; then links: [text](path) -> GitHub page.
s = s.replace(/!\[([^\]]*)\]\(([^)\s]+)\)/g, (m, alt, url) => (isRelative(url) ? `![${alt}](${RAW}${url})` : m));
s = s.replace(/(^|[^!])\[([^\]]*)\]\(([^)\s]+)\)/g, (m, pre, text, url) =>
  isRelative(url) ? `${pre}[${text}](${BLOB}${url})` : m);
s = s.replace(/src="([^"]+)"/g, (m, url) => (isRelative(url) ? `src="${RAW}${url}"` : m));
fs.writeFileSync(path.join(__dirname, "..", "README.md"), s);
console.log("synced README.md from the repo root");
