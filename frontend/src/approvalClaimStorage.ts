import { isRecord } from "./streamProtocol";

export type ApprovalClaim = {
  proposalRevisionId: string;
  requestId: string;
  requestedLeaseSeconds: number;
};

const CLAIM_STORAGE_PREFIX = "approval-workbench:claim:";

export function readApprovalClaim(approverId: string): ApprovalClaim | null {
  try {
    const raw = globalThis.sessionStorage.getItem(`${CLAIM_STORAGE_PREFIX}${approverId}`);
    if (!raw) return null;
    const value = JSON.parse(raw) as unknown;
    if (
      !isRecord(value) ||
      typeof value.proposalRevisionId !== "string" ||
      typeof value.requestId !== "string" ||
      typeof value.requestedLeaseSeconds !== "number"
    )
      return null;
    return {
      proposalRevisionId: value.proposalRevisionId,
      requestId: value.requestId,
      requestedLeaseSeconds: value.requestedLeaseSeconds,
    };
  } catch {
    return null;
  }
}

export function storeApprovalClaim(approverId: string, claim: ApprovalClaim) {
  try {
    globalThis.sessionStorage.setItem(
      `${CLAIM_STORAGE_PREFIX}${approverId}`,
      JSON.stringify(claim),
    );
  } catch {
    // The active page can still use the lease when browser storage is unavailable.
  }
}

export function clearApprovalClaim(approverId: string, requestId: string) {
  try {
    if (readApprovalClaim(approverId)?.requestId === requestId) {
      globalThis.sessionStorage.removeItem(`${CLAIM_STORAGE_PREFIX}${approverId}`);
    }
  } catch {
    // Storage failure must not change the authoritative decision or release result.
  }
}

export function clearApprovalClaims() {
  try {
    const keys: string[] = [];
    for (let index = 0; index < globalThis.sessionStorage.length; index += 1) {
      const key = globalThis.sessionStorage.key(index);
      if (key?.startsWith(CLAIM_STORAGE_PREFIX)) keys.push(key);
    }
    for (const key of keys) globalThis.sessionStorage.removeItem(key);
  } catch {
    // Session invalidation must still notify consumers when storage is unavailable.
  }
}
