import { existsSync } from "node:fs"
import { homedir } from "node:os"
import { join, resolve } from "node:path"
import { createInterface } from "node:readline"
import { spawn, type ChildProcessWithoutNullStreams } from "node:child_process"
import { tool, type Plugin } from "@opencode-ai/plugin"

type Pending = {
  resolve: (value: any) => void
  reject: (error: Error) => void
  timer: ReturnType<typeof setTimeout>
}

const doreHome = () => process.env.DORE_HOME || join(homedir(), "Documents", "dore")

const projectFor = (directory: string) => resolve(directory || ".")

let child: ChildProcessWithoutNullStreams | null = null
const pending = new Map<string, Pending>()
let seq = 0

const startBridge = () => {
  if (child && child.exitCode === null && !child.killed) return child
  const bin = join(doreHome(), ".venv", "bin", "dore-bridge")
  if (!existsSync(bin)) throw new Error(`dore-bridge not found at ${bin} (run the dore setup, or set DORE_HOME)`)
  const childProcess = spawn(bin, [], { stdio: ["pipe", "pipe", "pipe"], env: process.env })
  child = childProcess

  createInterface({ input: childProcess.stdout }).on("line", (line) => {
    let message: any
    try {
      message = JSON.parse(line)
    } catch {
      return
    }
    const waiter = pending.get(String(message.id))
    if (!waiter) return
    pending.delete(String(message.id))
    clearTimeout(waiter.timer)
    if (message.ok) waiter.resolve(message.result)
    else waiter.reject(new Error(message.error || "dore bridge error"))
  })

  childProcess.stderr.on("data", (data) => {
    const text = String(data).trim()
    if (text) console.error(`[dore] ${text}`)
  })

  childProcess.on("exit", () => {
    child = null
    for (const waiter of pending.values()) {
      clearTimeout(waiter.timer)
      waiter.reject(new Error("dore bridge exited"))
    }
    pending.clear()
  })

  return childProcess
}

const call = (op: string, payload: Record<string, any>, timeoutMs = 60_000): Promise<any> => {
  const process = startBridge()
  const id = String(++seq)
  return new Promise((resolvePromise, rejectPromise) => {
    const timer = setTimeout(() => {
      pending.delete(id)
      rejectPromise(new Error(`dore bridge timed out (${op})`))
    }, timeoutMs)
    pending.set(id, { resolve: resolvePromise, reject: rejectPromise, timer })
    process.stdin.write(JSON.stringify({ id, op, ...payload }) + "\n")
  })
}

export const DorePlugin: Plugin = async ({ directory }) => {
  const project = projectFor(directory)
  const pendingMessages = new Map<string, string[]>()
  const pendingNotes = new Map<string, Promise<string>>()
  const briefCache = new Map<string, string>()

  const flush = async (sessionID: string, messages: string[], where = project) => {
    if (!messages.length) return
    try {
      await call("learn", { messages, project: where })
    } catch (error) {
      console.error(`[dore] learn failed: ${error}`)
    }
  }

  return {
    tool: {
      dore_recall: tool({
        description:
          "Search dore long-term memory for past decisions, settings, locations, preferences. '#<id>' returns one full note.",
        args: {
          query: tool.schema.string(),
          project: tool.schema.string().optional(),
          k: tool.schema.number().int().min(1).max(10).optional(),
        },
        execute: async (args, context) => {
          try {
            return String(
              await call("recall", {
                query: args.query,
                project: args.project || projectFor(context.directory),
                k: args.k ?? 3,
              }),
            )
          } catch (error) {
            return `dore error: ${error}`
          }
        },
      }),
      dore_remember: tool({
        description:
          "Save short durable facts to dore memory, all in one call. user_said=true only for facts the user stated; your own conclusions stay unverified.",
        args: {
          facts: tool.schema.array(tool.schema.string()),
          project: tool.schema.string().optional(),
          user_said: tool.schema.boolean().optional(),
        },
        execute: async (args, context) => {
          try {
            return String(
              await call("remember", {
                facts: args.facts,
                project: args.project || projectFor(context.directory),
                user_said: args.user_said ?? false,
              }),
            )
          } catch (error) {
            return `dore error: ${error}`
          }
        },
      }),
      dore_correct: tool({
        description:
          "Mark wrong dore note ids as wrong (kept, not deleted) and save the correction. user_said=true if the user gave it.",
        args: {
          correction: tool.schema.string(),
          wrong_ids: tool.schema.array(tool.schema.number().int()),
          project: tool.schema.string().optional(),
          user_said: tool.schema.boolean().optional(),
        },
        execute: async (args, context) => {
          try {
            return String(
              await call("correct", {
                correction: args.correction,
                wrong_ids: args.wrong_ids,
                project: args.project || projectFor(context.directory),
                user_said: args.user_said ?? false,
              }),
            )
          } catch (error) {
            return `dore error: ${error}`
          }
        },
      }),
    },

    "chat.message": async (input, output) => {
      const sessionID = input.sessionID
      const text = output.parts
        .filter((part) => part.type === "text" && !part.synthetic)
        .map((part) => (part.type === "text" ? part.text : ""))
        .join("\n")
        .trim()
      if (!text) return
      const messages = pendingMessages.get(sessionID) || []
      messages.push(text)
      pendingMessages.set(sessionID, messages)
      pendingNotes.set(
        sessionID,
        call("prompt", { prompt: text, project, session_id: sessionID }, 20_000).catch((error) => {
          console.error(`[dore] prompt hook failed: ${error}`)
          return ""
        }),
      )
    },

    "experimental.chat.system.transform": async (input, output) => {
      const sessionID = input.sessionID
      if (!sessionID) return
      try {
        let brief = briefCache.get(sessionID)
        if (brief === undefined) {
          brief = String(await call("brief", { project }, 10_000))
          briefCache.set(sessionID, brief)
        }
        if (brief) output.system.push(brief)
      } catch (error) {
        console.error(`[dore] brief failed: ${error}`)
      }

      const notes = pendingNotes.get(sessionID)
      if (!notes) return
      pendingNotes.delete(sessionID)
      try {
        const text = await notes
        if (text) output.system.push(text)
      } catch (error) {
        console.error(`[dore] notes failed: ${error}`)
      }
    },

    event: async ({ event }) => {
      if (event.type === "session.idle") {
        const sessionID = event.properties.sessionID
        const messages = pendingMessages.get(sessionID) || []
        pendingMessages.delete(sessionID)
        await flush(sessionID, messages)
      } else if (event.type === "session.deleted") {
        const sessionID = event.properties.info.id
        const messages = pendingMessages.get(sessionID) || []
        pendingMessages.delete(sessionID)
        pendingNotes.delete(sessionID)
        briefCache.delete(sessionID)
        await flush(sessionID, messages)
      } else if (event.type === "session.compacted") {
        briefCache.delete(event.properties.sessionID)
      }
    },

    dispose: async () => {
      try {
        await call("close", {}, 2_000)
      } catch {
        // the child may already be gone
      }
      child?.kill()
      child = null
    },
  }
}

export default DorePlugin
