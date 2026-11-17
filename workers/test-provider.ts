// Deterministic provider and command used only by the workers-roles virtual-machine check
import { execFile, spawn } from "node:child_process";
import { writeFileSync } from "node:fs";
import { promisify } from "node:util";
import {
  createAssistantMessageEventStream,
  type AssistantMessage,
  type AssistantMessageEventStream,
  type Model,
  type SimpleStreamOptions,
  type TranscriptContext,
} from "@earendil-works/pi-ai";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

const execute = promisify(execFile);

function stream(
  model: Model<any>,
  context: TranscriptContext,
  options?: SimpleStreamOptions,
): AssistantMessageEventStream {
  const events = createAssistantMessageEventStream();
  const output: AssistantMessage = {
    role: "assistant",
    content: [],
    api: model.api,
    provider: model.provider,
    model: model.id,
    usage: {
      input: 0,
      output: 0,
      cacheRead: 0,
      cacheWrite: 0,
      totalTokens: 0,
      cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 },
    },
    stopReason: "pending",
    timestamp: Date.now(),
  };

  void (async () => {
    try {
      const last = context.messages.at(-1) as any;
      const text = JSON.stringify(last);
      if ((last?.role === "user") && text.includes("FOREGROUND")) {
        const toolCall = {
          type: "toolCall" as const,
          id: "foreground-job",
          name: "bash",
          arguments: { command: "queue run -- bash -c 'touch $WORKER_SCRATCH/foreground-started; sleep 2; touch $WORKER_SCRATCH/foreground-finished'" },
        };
        output.content.push(toolCall);
        output.stopReason = "toolUse";
        events.push({ type: "start", partial: output });
        events.push({ type: "toolcall_start", contentIndex: 0, partial: output });
        events.push({ type: "toolcall_end", contentIndex: 0, toolCall, partial: output });
        events.push({ type: "done", reason: "toolUse", message: output });
        events.end();
        return;
      }
      if (text.includes("SLOW")) {
        writeFileSync(`${process.env.WORKER_SCRATCH}/answer-started`, "started\n");
        await new Promise((resolve) => setTimeout(resolve, 2500));
      }
      if (options?.signal?.aborted) throw new Error("aborted");
      const answer = `WORKER-TEST-ANSWER MESSAGES=${context.messages.length} ${text}`;
      output.content.push({ type: "text", text: answer });
      output.stopReason = "stop";
      events.push({ type: "start", partial: output });
      events.push({ type: "text_start", contentIndex: 0, partial: output });
      events.push({ type: "text_delta", contentIndex: 0, delta: answer, partial: output });
      events.push({ type: "text_end", contentIndex: 0, content: answer, partial: output });
      events.push({ type: "done", reason: "stop", message: output });
      events.end();
      if (text.includes("SLOW")) writeFileSync(`${process.env.WORKER_SCRATCH}/answer-finished`, "finished\n", { flag: "a" });
    } catch (error) {
      output.stopReason = options?.signal?.aborted ? "aborted" : "error";
      output.errorMessage = error instanceof Error ? error.message : String(error);
      events.push({ type: "error", reason: output.stopReason, error: output });
      events.end();
    }
  })();

  return events;
}

export default function (pi: ExtensionAPI) {
  pi.on("session_start", (_event, ctx) => {
    try {
      writeFileSync("approval-write", "writable\n");
      ctx.ui.notify("PROBE-WRITE-OK", "info");
    } catch {
      // The initial locked sandbox is the control; the resumed sandbox succeeds
    }
  });

  pi.registerProvider("worker-test", {
    baseUrl: "http://worker-test.invalid",
    apiKey: "test-key",
    api: "worker-test-api",
    models: [
      {
        id: "deterministic",
        name: "Deterministic worker test",
        reasoning: false,
        input: ["text"],
        cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
        contextWindow: 32000,
        maxTokens: 1024,
      },
    ],
    streamSimple: stream,
  });

  pi.registerCommand("probe-write", {
    description: "Write one marker in the worker copy",
    handler: async (_args, ctx) => {
      try {
        writeFileSync("approval-write", "writable\n");
        ctx.ui.notify("PROBE-WRITE-OK", "info");
      } catch (error: any) {
        ctx.ui.notify(`PROBE-WRITE-REFUSED ${error?.code ?? String(error)}`, "error");
      }
    },
  });

  pi.registerCommand("detached-job", {
    description: "Leave one queued job for the old broker to stop",
    handler: async (_args, ctx) => {
      const child = spawn("queue", ["run", "--", "bash", "-c", "touch $WORKER_SCRATCH/detached-started; sleep 300"], {
        detached: true,
        stdio: "ignore",
      });
      child.unref();
      ctx.ui.notify("DETACHED-JOB-SUBMITTED", "info");
    },
  });

  pi.registerCommand("foreground-job", {
    description: "Run a foreground queued job for the restart check",
    handler: async (_args, ctx) => {
      await execute("queue", ["run", "--", "bash", "-c", "touch $WORKER_SCRATCH/foreground-started; sleep 2; touch $WORKER_SCRATCH/foreground-finished"]);
      ctx.ui.notify("FOREGROUND-JOB-FINISHED", "info");
    },
  });
}
