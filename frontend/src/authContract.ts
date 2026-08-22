export type HumanRole = "CUSTOMER" | "SUPPORT" | "APPROVER";
export type HumanCapability =
  "CUSTOMER_HELP_ACCESS" | "SUPPORT_WORKBENCH_ACCESS" | "APPROVAL_WORKBENCH_ACCESS";

export type CurrentSession = {
  id: string;
  displayName: string;
  subjectType: "CUSTOMER" | "INTERNAL";
  roles: HumanRole[];
  capabilities: HumanCapability[];
};
