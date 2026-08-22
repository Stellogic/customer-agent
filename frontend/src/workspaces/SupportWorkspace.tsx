import { SupportWorkbench } from "../SupportWorkbench";
import { LegacyBusinessIdentity } from "./LegacyBusinessIdentity";

const SUPPORT_IDS = ["support-demo"] as const;

export default function SupportWorkspace() {
  return (
    <LegacyBusinessIdentity
      role="SUPPORT"
      allowedIds={SUPPORT_IDS}
      deniedTitle="无权访问客服工作台"
    >
      {(supportId) => <SupportWorkbench supportId={supportId} />}
    </LegacyBusinessIdentity>
  );
}
