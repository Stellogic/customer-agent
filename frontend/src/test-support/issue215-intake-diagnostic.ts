export const diagnosticKinds = ["PACKAGE_NOT_RECEIVED", "DUPLICATE_CHARGE"] as const;
export type DiagnosticKind = (typeof diagnosticKinds)[number];

export interface IntakeObservation {
  httpStatus: number;
  status: string;
  candidateMatches: boolean;
  responseIssueKinds: string[];
  issueKinds: string[];
  pendingKinds: string[];
  assistanceCount: number;
  ticketCount: number;
}

const same = (left: string[], right: string[]) =>
  left.length === right.length && left.every((value, index) => value === right[index]);

export function assessIntakeProgress(initial: IntakeObservation, followup?: IntakeObservation) {
  if (
    initial.httpStatus !== 201 ||
    initial.status !== (initial.pendingKinds.length ? "NEEDS_CLARIFICATION" : "READY_TO_CONFIRM") ||
    !initial.candidateMatches ||
    initial.assistanceCount !== 0 ||
    initial.ticketCount !== 0 ||
    !same(initial.responseIssueKinds, initial.issueKinds) ||
    !same([...initial.issueKinds, ...initial.pendingKinds].sort(), [...diagnosticKinds].sort())
  ) {
    return "INITIAL_PRECONDITION_FAILED";
  }
  if (!followup) return initial.pendingKinds.length ? "READY_TO_REPLY" : "READY_TO_CONFIRM";
  if (!initial.pendingKinds.length) return "PROGRESS_MISMATCH";
  if (followup.assistanceCount !== 0) return "ASSISTED";
  if (followup.ticketCount !== 0) return "PREMATURE_TICKET";
  if (
    followup.httpStatus !== 201 ||
    followup.status !==
      (initial.pendingKinds.length === 1 ? "READY_TO_CONFIRM" : "NEEDS_CLARIFICATION") ||
    !followup.candidateMatches ||
    !same(followup.responseIssueKinds, [...initial.issueKinds, initial.pendingKinds[0]]) ||
    !same(followup.issueKinds, [...initial.issueKinds, initial.pendingKinds[0]]) ||
    !same(followup.pendingKinds, initial.pendingKinds.slice(1))
  ) {
    return "PROGRESS_MISMATCH";
  }
  return "HEAD_ADVANCED";
}
