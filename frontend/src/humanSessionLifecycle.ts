import { parseCurrentSession, type CurrentSession } from "./authContract";

export type HumanSessionInvalidationReason = "logged-out" | "subject-replaced" | "server-rejected";

type ObservedHumanSession = Pick<CurrentSession, "id" | "subjectType" | "roles" | "capabilities">;

type HumanSessionChange = {
  reason: HumanSessionInvalidationReason;
  nonce: string;
};

const CHANNEL_NAME = "customer-agent-human-session";
const STORAGE_KEY = "customer-agent:human-session-change";
const listeners = new Set<(reason: HumanSessionInvalidationReason) => void>();
let channel: BroadcastChannel | undefined;
let storageListening = false;
let observedSessionFingerprint: string | undefined;

export function observeHumanSession(session: ObservedHumanSession | undefined) {
  observedSessionFingerprint = session ? sessionFingerprint(session) : undefined;
}

export function subscribeToHumanSessionInvalidation(
  listener: (reason: HumanSessionInvalidationReason) => void,
) {
  listeners.add(listener);
  ensureCrossTabListeners();
  return () => {
    listeners.delete(listener);
    if (listeners.size === 0) closeCrossTabListeners();
  };
}

export function announceHumanSessionChange(reason: HumanSessionInvalidationReason) {
  const change: HumanSessionChange = {
    reason,
    nonce: globalThis.crypto.randomUUID(),
  };
  invalidateCurrentTab(change.reason);
  if (channel) channel.postMessage(change);
  else if (typeof globalThis.BroadcastChannel === "function") {
    const sender = new globalThis.BroadcastChannel(CHANNEL_NAME);
    sender.postMessage(change);
    sender.close();
  }
  try {
    globalThis.localStorage?.setItem(STORAGE_KEY, JSON.stringify(change));
  } catch {
    // BroadcastChannel remains the primary same-origin signal. Server rejection is authoritative.
  }
}

export async function humanSessionFetch(input: RequestInfo | URL, init?: RequestInit) {
  const response = await globalThis.fetch(input, init);
  if (response.status === 401) invalidateCurrentTab("server-rejected");
  else if (response.status === 403 || response.status === 404) {
    await convergeWithAuthoritativeSession();
  }
  return response;
}

async function convergeWithAuthoritativeSession() {
  if (!observedSessionFingerprint) return;
  try {
    const response = await globalThis.fetch("/api/auth/session", {
      credentials: "same-origin",
      cache: "no-store",
    });
    if (response.status === 401) {
      invalidateCurrentTab("server-rejected");
      return;
    }
    if (!response.ok) return;
    const current = parseCurrentSession(await response.json());
    if (current && sessionFingerprint(current) !== observedSessionFingerprint) {
      invalidateCurrentTab("subject-replaced");
    }
  } catch {
    // A later authoritative request or SSE reconnect will retry convergence.
  }
}

function sessionFingerprint(session: ObservedHumanSession) {
  return JSON.stringify([
    session.id,
    session.subjectType,
    [...session.roles].sort(),
    [...session.capabilities].sort(),
  ]);
}

function ensureCrossTabListeners() {
  if (!channel && typeof globalThis.BroadcastChannel === "function") {
    channel = new globalThis.BroadcastChannel(CHANNEL_NAME);
    channel.addEventListener("message", (event: MessageEvent<unknown>) => {
      const change = parseChange(event.data);
      if (change) invalidateCurrentTab(change.reason);
    });
  }
  if (!storageListening && typeof globalThis.addEventListener === "function") {
    globalThis.addEventListener("storage", receiveStorageChange);
    storageListening = true;
  }
}

function receiveStorageChange(event: StorageEvent) {
  if (event.key !== STORAGE_KEY || !event.newValue) return;
  try {
    const change = parseChange(JSON.parse(event.newValue) as unknown);
    if (change) invalidateCurrentTab(change.reason);
  } catch {
    // Ignore malformed same-origin storage values.
  }
}

function parseChange(value: unknown): HumanSessionChange | undefined {
  if (!value || typeof value !== "object") return undefined;
  const candidate = value as Partial<HumanSessionChange>;
  if (
    !["logged-out", "subject-replaced", "server-rejected"].includes(String(candidate.reason)) ||
    typeof candidate.nonce !== "string"
  )
    return undefined;
  return candidate as HumanSessionChange;
}

function invalidateCurrentTab(reason: HumanSessionInvalidationReason) {
  for (const listener of listeners) listener(reason);
}

export function resetHumanSessionLifecycleForTests() {
  listeners.clear();
  observedSessionFingerprint = undefined;
  closeCrossTabListeners();
}

function closeCrossTabListeners() {
  channel?.close();
  channel = undefined;
  if (storageListening) globalThis.removeEventListener("storage", receiveStorageChange);
  storageListening = false;
}
