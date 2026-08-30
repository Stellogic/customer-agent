export type PendingSupportReply = { idempotencyKey: string; body: string };

const PENDING_REPLY_STORAGE_PREFIX = "support-workbench:pending-reply:";

export function readPendingReply(ticketId: string): PendingSupportReply | null {
  try {
    const raw = globalThis.sessionStorage.getItem(pendingReplyStorageKey(ticketId));
    if (!raw) return null;
    const value = JSON.parse(raw) as unknown;
    if (
      !isRecord(value) ||
      typeof value.idempotencyKey !== "string" ||
      value.idempotencyKey.trim().length === 0 ||
      value.idempotencyKey.length > 200 ||
      typeof value.body !== "string" ||
      value.body.trim().length === 0 ||
      value.body.length > 2000
    )
      return null;
    return { idempotencyKey: value.idempotencyKey, body: value.body };
  } catch {
    return null;
  }
}

export function storePendingReply(ticketId: string, reply: PendingSupportReply) {
  try {
    globalThis.sessionStorage.setItem(pendingReplyStorageKey(ticketId), JSON.stringify(reply));
  } catch {
    // Query remains available during this render even if browser storage is unavailable.
  }
}

export function clearPendingReply(ticketId: string) {
  try {
    globalThis.sessionStorage.removeItem(pendingReplyStorageKey(ticketId));
  } catch {
    // Storage failures must not change the authoritative reply result.
  }
}

export function clearPendingSupportReplies() {
  try {
    const keys: string[] = [];
    for (let index = 0; index < globalThis.sessionStorage.length; index += 1) {
      const key = globalThis.sessionStorage.key(index);
      if (key?.startsWith(PENDING_REPLY_STORAGE_PREFIX)) keys.push(key);
    }
    for (const key of keys) globalThis.sessionStorage.removeItem(key);
  } catch {
    // Session invalidation must still notify consumers when storage is unavailable.
  }
}

function pendingReplyStorageKey(ticketId: string) {
  return `${PENDING_REPLY_STORAGE_PREFIX}${ticketId}`;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
