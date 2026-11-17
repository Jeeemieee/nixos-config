// Gracefully leave a locked pi sandbox after approval; the outside supervisor resumes the saved chat in a fresh view
import { existsSync, readFileSync } from "node:fs";
import { createConnection } from "node:net";
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";

const requestPath = "/run/worker-control/restart";
const startedPath = "/run/worker-control/started";
const pendingType = "worker-approval-restart";
const consumedType = "worker-approval-restart-consumed";

export default function (pi: ExtensionAPI) {
  let timer: ReturnType<typeof setInterval> | undefined;
  let stopping = false;
  let nonce = "";

  const editorText = (ctx: ExtensionContext): string => (ctx.hasUI ? ctx.ui.getEditorText() : "");

  const acknowledge = (startedNonce: string) => {
    const connection = createConnection(startedPath);
    connection.setTimeout(250, () => connection.destroy());
    connection.once("connect", () => connection.end(`${startedNonce}\n`));
    connection.once("error", () => connection.destroy());
  };

  const remember = (ctx: ExtensionContext) => {
    if (nonce) pi.appendEntry(pendingType, { nonce, editorText: editorText(ctx) });
  };

  const check = (ctx: ExtensionContext) => {
    if (stopping || !existsSync(requestPath)) return;
    try {
      const request = JSON.parse(readFileSync(requestPath, "utf8"));
      if (typeof request.nonce !== "string" || request.nonce.length < 16) return;
      nonce = request.nonce;
    } catch {
      return;
    }
    stopping = true;
    remember(ctx);
    if (ctx.hasUI) {
      ctx.ui.notify("Approval opened the copy; this answer and chat will be saved, then pi will continue automatically.", "info");
    }
    ctx.shutdown();
  };

  pi.on("session_start", (_event, ctx) => {
    let pending: { nonce: string; editorText: string } | undefined;
    const consumed = new Set<string>();
    for (const entry of ctx.sessionManager.getEntries()) {
      if (entry.type !== "custom") continue;
      if (entry.customType === consumedType && typeof (entry.data as any)?.nonce === "string") {
        consumed.add((entry.data as any).nonce);
      } else if (entry.customType === pendingType && typeof (entry.data as any)?.nonce === "string") {
        pending = {
          nonce: (entry.data as any).nonce,
          editorText: typeof (entry.data as any)?.editorText === "string" ? (entry.data as any).editorText : "",
        };
      }
    }
    if (pending && !consumed.has(pending.nonce)) {
      if (ctx.hasUI && pending.editorText) ctx.ui.setEditorText(pending.editorText);
      pi.appendEntry(consumedType, { nonce: pending.nonce });
      acknowledge(pending.nonce);
      if (ctx.hasUI) ctx.ui.notify("Approval continuation restored your unsubmitted editor text.", "info");
    }
    check(ctx);
    timer = setInterval(() => check(ctx), 200);
  });

  pi.on("session_shutdown", (_event, ctx) => {
    if (timer) clearInterval(timer);
    if (stopping) remember(ctx);
  });
}
