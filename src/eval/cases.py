"""Labelled messages for testing what dore learns, in many writing styles (not one person's words).

Two independent sets, written separately:
- DEV: web shop / backend work. Rules may be designed while looking at these.
- HELDOUT: mobile, data, devops, embedded, ML and personal life, in other wording. Only measured,
  never used to design or tune a rule. A rule that passes DEV but not HELDOUT is a word patch.
A third set, real prompts from the user's own Claude Code sessions, stays in `data/` (private,
git-ignored) and is also only measured (`python -m dore.eval.learning --real`).

Each case: (message, expect, scope, style)
- expect: a value that must appear in a stored note ("" = nothing may be stored; None = ambiguous, not scored)
- scope: "project" or "general" (about the user or the whole organisation), for facts only
- style: plain, casual, typo, non-native, terse, polite, mixed (a fact inside a request), correction,
  request, question, reaction, opinion, progress, paste, log, code, ui, chatter, hypothetical, other-language
"""

from __future__ import annotations

DEV = [
    # durable project facts
    ("The API runs on port 8080.", "8080", "project", "plain"),
    ("This project uses PostgreSQL as its database.", "PostgreSQL", "project", "plain"),
    ("we deploy to heroku", "heroku", "project", "casual"),
    ("The main branch is called develop.", "develop", "project", "plain"),
    ("Tests are run with pytest, not unittest.", "pytest", "project", "plain"),
    ("Max discount is 50% because finance said so.", "50%", "project", "plain"),
    ("the staging db is on 10.0.3.7", "10.0.3.7", "project", "casual"),
    ("Payments go through Stripe.", "Stripe", "project", "terse"),
    ("Our frontend is written in React 18 with Vite.", "React", "project", "plain"),
    ("this repo uses pnpm for packages", "pnpm", "project", "casual"),
    ("The admin panel lives under /admin and needs the staff role.", "/admin", "project", "plain"),
    ("Product images are stored in an S3 bucket called shop-media.", "shop-media", "project", "plain"),
    ("we decided to keep the cart in redis", "redis", "project", "casual"),
    ("The build takes about 4 minutes on CI.", "4 minutes", "project", "plain"),
    ("Prices are in cents everywhere in the code.", "cents", "project", "plain"),
    ("I set the dev server to port 3001.", "3001", "project", "plain"),
    ("I configured the linter to allow 120 character lines.", "120", "project", "plain"),
    # personal / general facts and lasting preferences
    ("My name is Dara.", "Dara", "general", "plain"),
    ("I prefer short answers without emojis.", "short", "general", "plain"),
    ("i use neovim as my editor", "neovim", "general", "casual"),
    ("I work from Phnom Penh, so my timezone is UTC+7.", "UTC+7", "general", "plain"),
    ("Always use spaces, never tabs.", "spaces", "general", "terse"),
    ("i dont like long explanations, keep it simple", "simple", "general", "typo"),
    ("Our production server runs Ubuntu 22.04.", "22.04", "general", "plain"),
    ("We never push to main on Fridays.", "Fridays", "general", "plain"),
    # facts in non-native or typo-heavy English
    ("my laptop are macbook air m2", "macbook", "general", "non-native"),
    ("this project database are mysql 8", "mysql", "project", "non-native"),
    ("the backend api write by fastapi", "fastapi", "project", "non-native"),
    ("we hosting the site on vercel", "vercel", "project", "non-native"),
    ("i alway write test with jest", "jest", "general", "typo"),
    # a fact inside a request
    ("hey can you set up the cart page? fyi we style everything with Tailwind.", "Tailwind", "project", "mixed"),
    ("add a login form, the auth provider is Auth0", "Auth0", "project", "mixed"),
    ("Please remember that the client wants dark mode by default.", "dark mode", "project", "polite"),
    # corrections
    ("No, the API runs on port 9090 now.", "9090", "project", "correction"),
    ("actually we moved the database to MySQL", "MySQL", "project", "correction"),
    ("Not quite, the discount cap is 40%.", "40%", "project", "correction"),
    # requests (nothing to store)
    ("add tests for cart.py", "", None, "request"),
    ("use a dataclass instead", "", None, "request"),
    ("make it async", "", None, "request"),
    ("Could you refactor the checkout flow into smaller functions?", "", None, "request"),
    ("rename x to total in calc.py", "", None, "request"),
    ("looks good, now update the README", "", None, "request"),
    ("go with the second option", "", None, "request"),
    ("i want the button to be bigger and blue", "", None, "non-native"),
    ("i need a page that show all order of today", "", None, "non-native"),
    ("can it have sound when scan wrong product", "", None, "non-native"),
    ("For the table use card style like the other page", "", None, "request"),
    ("Now turn it on and show it on the status line too", "", None, "request"),
    ("just give me the command", "", None, "request"),
    ("Switch the chart to a bar chart.", "", None, "request"),
    # questions, with and without "?"
    ("What does this function return?", "", None, "question"),
    ("how to setup this on github action", "", None, "question"),
    ("is this good or not", "", None, "question"),
    ("why the page so slow", "", None, "non-native"),
    ("Which one is better for us, Redis or Memcached?", "", None, "question"),
    # reactions, progress, opinions about the current work
    ("hmm that's not right, the test still fails", "", None, "reaction"),
    ("it still fails with the same error", "", None, "progress"),
    ("perfect, that works", "", None, "reaction"),
    ("I think the bug is in utils.py.", "", None, "opinion"),
    ("I don't like this approach, try something simpler.", "", None, "opinion"),
    ("seem the card are too small", "", None, "non-native"),
    ("The page looks weird on mobile.", "", None, "reaction"),
    ("This test is flaky, it passed on the second run.", "", None, "progress"),
    ("I feel the UI is hard to read", "", None, "opinion"),
    ("still not working", "", None, "progress"),
    ("Now it's a bit slower than before.", "", None, "progress"),
    # chatter, system text, hypotheticals
    ("thanks!", "", None, "chatter"),
    ("ok", "", None, "chatter"),
    ("[Request interrupted by user]", "", None, "chatter"),
    ("/clear", "", None, "chatter"),
    ("If I were rich I would buy a server farm.", "", None, "hypothetical"),
    # pastes: logs, code, assistant output, UI text, docs
    ("what does this mean\nTraceback (most recent call last):\n  File \"cart.py\", line 12, in <module>\n"
     "    main()\nKeyError: 'user_id'", "", None, "log"),
    ("Error: connect ECONNREFUSED 127.0.0.1:5432\n    at TCPConnectWrap.afterConnect [as oncomplete] "
     "(node:net:1555:16)", "", None, "log"),
    ("def total(items):\n    return sum(i.price for i in items)", "", None, "code"),
    ("**MEDIUM: truncated saves get through (`lib/store.cpp:14`).**\n- The writer returns `n` even if "
     "`concat` failed.\n- Fix: check the return value before replacing the file.", "", None, "paste"),
    ("Here are my findings.\n\n1. The cache is never cleared.\n2. The retry loop has no limit.\n"
     "3. Logging is disabled in production.", "", None, "paste"),
    ("● Claude Code  ● opencode\n● 1 API key   DEEPSEEK_API_KEY\nAgents    Claude Code · opencode",
     "", None, "ui"),
    ("✅ Watcher started.\nShowing the 5 newest matches; future runs send only new items.", "", None, "ui"),
    ("Pageviews / web analytics: traffic, top pages, referrers and device.\nFunnels: an ordered set of "
     "events, for example view → add to cart → purchase.\nHeatmaps: where people tap or click.",
     "", None, "paste"),
    ('{"name": "shop", "version": "1.2.0", "private": true}', "", None, "code"),
    # other languages (bge-small is English-only: expected to fail today, measured anyway)
    ("ខ្ញុំរស់នៅភ្នំពេញ", "ភ្នំពេញ", "general", "other-language"),
    ("Nous utilisons PostgreSQL pour la base de données.", "PostgreSQL", "project", "other-language"),
    # added after error analysis (own wording, not the user's): facts in reason clauses, possibility,
    # intent, objects that are only "it", 2-line pastes, "i mean", dropped "is"
    ("please check the deploy script since we host on Fly.io", "Fly.io", "project", "mixed"),
    ("can you look at the cron job, because our backups run at 3am", "3am", "project", "mixed"),
    ("fix the login since i use firefox for testing", "firefox", "general", "mixed"),
    ("This connection may not be private.", "", None, "paste"),
    ("The import could be slow.", "", None, "opinion"),
    ("I can push it after lunch.", "", None, "progress"),
    ("we will look into the cache later", "", None, "progress"),
    ("ok i like it", "", None, "reaction"),
    ("i mean move it to the top like the other page", "", None, "non-native"),
    ("✔ Server started.\nListening for changes on 4 files", "", None, "ui"),
    ("our api hosted in frankfurt region", "frankfurt", "project", "non-native"),
    # added after the full real replay (own wording): politeness anywhere, statement-shaped questions,
    # shell commands and error chains, "I ... this"
    ("check is there any secret left in the repo please", "", None, "non-native"),
    ("the chart and the table are should be fix for me pls", "", None, "non-native"),
    ("the tests are slow on ci or not", "", None, "question"),
    ("this config is the final one, right", "", None, "question"),
    ("sudo systemctl restart nginx && sudo nginx -t", "", None, "code"),
    ("bash: pnpm: command not found", "", None, "log"),
    ("I added this to my zshrc", "", None, "progress"),
    ("i still dont understanding the error", "", None, "non-native"),
    ("we self-host sentry, so please check the dsn", "sentry", "project", "mixed"),
    ("Because the menu is slow on old phones", "", None, "non-native"),
    ("after i click save when ever the modal close", "", None, "non-native"),
    ("On v2 seem the spacing of icons too wide", "", None, "non-native"),
    ("10 PM now are 22", "", None, "non-native"),
    ("i wnat to add a filter for unpaid bills", "", None, "typo"),
    ("I should try the second option", "", None, "progress"),
    ("Status · paid · due soon", "", None, "ui"),
    # ambiguous: not scored
    ("Don't run the local model, just use Claude Code now.", None, None, "ambiguous"),
]

HELDOUT = [
    # durable project facts (other domains, other wording)
    ("The Android app targets SDK 34.", "34", "project", "plain"),
    ("Our iOS build needs Xcode 15.2 or newer.", "15.2", "project", "plain"),
    ("data pipeline runs every night at 2am", "2am", "project", "casual"),
    ("The warehouse is BigQuery; raw events land in the events_raw dataset.", "BigQuery", "project", "plain"),
    ("Firmware is flashed over UART at 115200 baud.", "115200", "project", "plain"),
    ("the board is an ESP32-S3 with 8MB PSRAM", "ESP32-S3", "project", "casual"),
    ("Kubernetes namespace for this service is billing-prod.", "billing-prod", "project", "plain"),
    ("Terraform state is kept in the tf-state bucket.", "tf-state", "project", "plain"),
    ("Model checkpoints go to /mnt/ckpt.", "/mnt/ckpt", "project", "terse"),
    ("We train with a batch size of 64.", "64", "project", "plain"),
    ("The mobile app talks to the gateway at api.example.org.", "api.example.org", "project", "plain"),
    ("Feature flags are managed in LaunchDarkly.", "LaunchDarkly", "project", "plain"),
    ("release branches are named release/x.y", "release/x.y", "project", "casual"),
    ("Logs are shipped to Loki and kept for 14 days.", "14 days", "project", "plain"),
    ("I bumped the Gradle wrapper to 8.5 last week.", "8.5", "project", "plain"),
    ("I keep the secrets in 1Password, not in .env files.", "1Password", "general", "plain"),
    ("Translations live in locales/km.json and locales/en.json.", "locales", "project", "plain"),
    # personal / general
    ("Call me Sok.", "Sok", "general", "terse"),
    ("I'm colorblind, so please don't rely on red vs green.", "colorblind", "general", "plain"),
    ("my keyboard layout is dvorak", "dvorak", "general", "casual"),
    ("I usually code late at night, after 10pm.", "10pm", "general", "plain"),
    ("I'm a backend developer, mostly Go.", "Go", "general", "plain"),
    ("English is my second language.", "second language", "general", "plain"),
    ("Our company uses Google Workspace for email.", "Google Workspace", "general", "plain"),
    ("All our services must log in JSON.", "JSON", "general", "plain"),
    ("I like answers with a code example first.", "code example", "general", "plain"),
    # non-native / typos
    ("the app are use flutter 3.19", "flutter", "project", "non-native"),
    ("our server located in singapore region", "singapore", "project", "non-native"),
    ("i am using windows 11 with wsl", "windows 11", "general", "non-native"),
    ("this projet use mongodb atlas free tier", "mongodb", "project", "typo"),
    ("teh printer is epson tm-t82", "tm-t82", "project", "typo"),
    ("my phone is samsung a54 for testing", "a54", "general", "non-native"),
    # mixed, polite, corrections
    ("could you fix the login crash? btw the backend is Django 5", "Django", "project", "mixed"),
    ("pls add a retry, the queue is RabbitMQ", "RabbitMQ", "project", "mixed"),
    ("Just so you know, the client pays per seat.", "per seat", "project", "polite"),
    ("Note that staging resets every Monday.", "Monday", "project", "polite"),
    ("nope, the baud rate is 9600", "9600", "project", "correction"),
    ("Wrong, we target SDK 35 now.", "35", "project", "correction"),
    ("Correction: the bucket is called tf-state-eu.", "tf-state-eu", "project", "correction"),
    # requests
    ("Bump the version to 2.1.0", "", None, "request"),
    ("put the logo in the top left", "", None, "request"),
    ("Let's split this into two PRs.", "", None, "request"),
    ("drop the unused imports", "", None, "request"),
    ("Kindly regenerate the API client.", "", None, "polite"),
    ("I'd like a dark theme for the settings screen.", "", None, "request"),
    ("we need an export to csv button", "", None, "request"),
    ("i want it scan faster and show the result on top", "", None, "non-native"),
    ("Show me the diff.", "", None, "request"),
    ("revert that", "", None, "request"),
    ("Translate the error messages to Khmer.", "", None, "request"),
    ("Do the same for the iOS app.", "", None, "request"),
    # questions
    ("Is the bucket public?", "", None, "question"),
    ("what is the best way to cache this", "", None, "question"),
    ("any idea why the build is red", "", None, "question"),
    ("Should we use gRPC here", "", None, "question"),
    ("this one correct or not", "", None, "non-native"),
    # reactions, progress, opinions
    ("nice, works now", "", None, "reaction"),
    ("Still crashing on startup.", "", None, "progress"),
    ("The colors look off.", "", None, "reaction"),
    ("I guess the problem is the timeout.", "", None, "opinion"),
    ("I'm not sure this is the right fix.", "", None, "opinion"),
    ("the build passed this time", "", None, "progress"),
    ("Hmm, weird.", "", None, "reaction"),
    ("seem it slower than yesterday", "", None, "non-native"),
    ("I don't understand this part.", "", None, "opinion"),
    ("That's way better.", "", None, "reaction"),
    # chatter, hypotheticals
    ("good morning", "", None, "chatter"),
    ("cool cool", "", None, "chatter"),
    ("Imagine we had a million users.", "", None, "hypothetical"),
    ("Suppose the cache is down, what happens?", "", None, "hypothetical"),
    # pastes
    ("E/AndroidRuntime: FATAL EXCEPTION: main\nProcess: com.example.app, PID: 4821\n"
     "java.lang.NullPointerException: Attempt to invoke virtual method", "", None, "log"),
    ("$ kubectl get pods\nNAME                     READY   STATUS    RESTARTS   AGE\n"
     "billing-7d9f8b-x2k4l     1/1     Running   0          3d", "", None, "log"),
    ("SELECT user_id, count(*) FROM events GROUP BY 1 ORDER BY 2 DESC LIMIT 10;", "", None, "code"),
    ("## Summary\n- Added retry with backoff to the uploader.\n- Moved config into `settings.toml`.\n"
     "- Tests: 42 passed.", "", None, "paste"),
    ("The function `parse_row` in `etl/rows.py:88` drops rows whose timestamp is empty, so the daily "
     "count is low by about 3%.", "", None, "paste"),
    ("Step 1: open Settings.\nStep 2: tap Developer options.\nStep 3: enable USB debugging.", "", None, "paste"),
    ("[INFO] 2026-11-20 02:00:01 job=nightly rows=120394 status=ok", "", None, "log"),
    ("warning: unused variable `x`\n --> src/main.rs:4:9", "", None, "log"),
    # other languages
    ("ខ្ញុំប្រើ Python សម្រាប់គម្រោងនេះ", "Python", "project", "other-language"),
    ("Usamos MySQL en producción.", "MySQL", "project", "other-language"),
]

# Updates: (old, new, must_replace, style). A replace hides the old note (kept in SQLite).
UPDATES = [
    ("The API runs on port 8080.", "The API runs on port 9090 now.", True, "same words + now"),
    ("We deploy to Heroku.", "We deploy to Render now.", True, "verb not in a list"),
    ("My editor is Neovim.", "I switched my editor to Helix.", True, "reworded"),
    ("The database is PostgreSQL.", "We moved the database to MySQL.", True, "reworded"),
    ("The Android app targets SDK 34.", "The Android app targets SDK 35.", True, "same words"),
    ("The board is an ESP32.", "We changed the board to an RP2040.", True, "reworded"),
    ("Staging resets every Monday.", "Staging resets every Sunday now.", True, "same words + now"),
    ("Logs are kept for 14 days.", "Logs are kept for 30 days.", True, "same words"),
    # must keep both
    ("I have a dog called Buddy.", "I have a dog called Max.", False, "multi-value"),
    ("Sophal works on the mobile team.", "Piseth works on the mobile team.", False, "different subject"),
    ("The API runs on port 8080.", "The admin panel runs on port 8081.", False, "different subject"),
    ("My car is red.", "I bought my car in 2020.", False, "different detail"),
    ("We use pytest for tests.", "We use ruff for linting.", False, "different role"),
    ("The API runs on port 8080.", "The API needs Python 3.11.", False, "different detail"),
    ("The report is due on Friday.", "I sent the report to Dara.", False, "'to' that is not a change"),
    ("We deploy the web app to Netlify.", "We deploy the docs to GitHub Pages.", False, "different subject after verb"),
    ("I visited Japan in 2019.", "I visited Korea in 2022.", False, "multi-value"),
    ("Sok reviews the backend PRs.", "Dara reviews the backend PRs.", False, "different subject"),
    ("We fixed bug 12 in the parser.", "We fixed bug 13 in the parser.", False, "events pile up"),
]

# Retrieval: (stored note, question asked later, style). The note should be shown for the question.
RETRIEVAL = [
    ("I prefer short answers without emojis.", "How long should your answers be?", "rephrased"),
    ("My editor is Helix now.", "Which editor do I use?", "after update"),
    ("We deploy to Render now.", "Where does this project deploy to?", "after update"),
    ("I work as a nurse at Calmette Hospital.", "What is my job?", "rephrased"),
    ("The API runs on port 9090.", "what port is the api on", "casual"),
    ("Product images are stored in an S3 bucket called shop-media.", "where do the product pictures go",
     "rephrased"),
    ("Firmware is flashed over UART at 115200 baud.", "What baud rate should I use to flash?", "rephrased"),
    ("Tests are run with pytest, not unittest.", "How do I run the tests here?", "rephrased"),
]
