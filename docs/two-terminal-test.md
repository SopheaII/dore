# Two-terminal test

## Before you start

Make two folders in Downloads, **alpha** and **beta**, by pasting this once:

```bash
mkdir -p ~/Downloads/dore-test/alpha ~/Downloads/dore-test/beta
cd ~/Downloads/dore-test/alpha && git init -q
cd ~/Downloads/dore-test/beta && git init -q
```

Wait a few seconds after each message before typing in the other terminal.

---

## Test 1: same project (both terminals in alpha)

Terminal 1: `cd ~/Downloads/dore-test/alpha && claude`
Terminal 2: `cd ~/Downloads/dore-test/alpha && claude`

| Step | Where | Type | Should happen |
|---|---|---|---|
| 1 | Terminal 1 | `The alpha API runs on port 7311.` | Claude says OK |
| 2 | Terminal 2 | `What port does the alpha API run on?` | Claude says **7311** |
| 3 | Terminal 2 | `The alpha API port is now 7412.` | Claude says OK |
| 4 | Terminal 1 | `Which port does the API use?` | Claude says **7412** (not 7311) |
| 5 | Terminal 1 | `In this project always use pnpm, never npm.` | Claude says OK |
| 6 | Terminal 2 | `Add the lodash package to the project.` | Claude uses **pnpm** |

## Test 2: different projects (terminal 2 moves to beta)

Close terminal 2, then open it again: `cd ~/Downloads/dore-test/beta && claude`

| Step | Where | Type | Should happen |
|---|---|---|---|
| 7 | Terminal 2 (beta) | `What port does the API run on?` | Claude **does not know** |
| 8 | Terminal 2 (beta) | `Add the lodash package.` | Claude does **not** mention pnpm |
| 9 | Terminal 2 (beta) | `The beta database is Postgres 16.` | Claude says OK |
| 10 | Terminal 1 (alpha) | `Which database does this project use?` | Claude **does not know** Postgres 16 |
| 11 | Terminal 1 (alpha) | `My favourite fruit is mango.` | Claude says OK |
| 12 | Terminal 2 (beta) | `What is my favourite fruit?` | Claude says **mango** |
| 13 | Terminal 2 (beta) | `Actually my favourite fruit is papaya now.` | Claude says OK |
| 14 | Terminal 1 (alpha) | `What is my favourite fruit?` | Claude says **papaya** |
| 15 | Terminal 2 (beta) | `The beta API runs on port 9000.` | Claude says OK |
| 16 | Terminal 1 (alpha) | `What port does the API run on?` | Claude still says **7412** |

## Is it working?

| What | Good if |
|---|---|
| Same project shares notes | Steps 2, 4, 6 are right |
| Projects stay separate | Steps 7, 8, 10, 16 are right |
| Things about **you** go everywhere | Steps 12, 14 are right |

## When finished

```bash
rm -rf ~/Downloads/dore-test
```
