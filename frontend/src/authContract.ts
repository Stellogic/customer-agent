export type HumanRole = "CUSTOMER" | "SUPPORT" | "APPROVER";
export type HumanCapability =
  | "CUSTOMER_HELP_ACCESS"
  | "SUPPORT_WORKBENCH_ACCESS"
  | "APPROVAL_WORKBENCH_ACCESS"
  | "KNOWLEDGE_READ_ACCESS";

export type CurrentSession = {
  id: string;
  displayName: string;
  subjectType: "CUSTOMER" | "INTERNAL";
  roles: HumanRole[];
  capabilities: HumanCapability[];
};

export function parseCurrentSession(value: unknown): CurrentSession | undefined {
  if (!isRecord(value)) return undefined;
  if (
    !Object.keys(value).every((key) =>
      ["id", "displayName", "subjectType", "roles", "capabilities"].includes(key),
    ) ||
    typeof value.id !== "string" ||
    typeof value.displayName !== "string" ||
    (value.subjectType !== "CUSTOMER" && value.subjectType !== "INTERNAL") ||
    !Array.isArray(value.roles) ||
    !value.roles.every((entry) => ["CUSTOMER", "SUPPORT", "APPROVER"].includes(String(entry))) ||
    !Array.isArray(value.capabilities) ||
    !value.capabilities.every((entry) =>
      [
        "CUSTOMER_HELP_ACCESS",
        "SUPPORT_WORKBENCH_ACCESS",
        "APPROVAL_WORKBENCH_ACCESS",
        "KNOWLEDGE_READ_ACCESS",
      ].includes(String(entry)),
    )
  )
    return undefined;
  return value as CurrentSession;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
