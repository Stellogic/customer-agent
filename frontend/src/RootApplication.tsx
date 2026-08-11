import { App } from "./App";
import { SupportWorkbench } from "./SupportWorkbench";

export function RootApplication() {
  return globalThis.location.pathname === "/support" ? <SupportWorkbench /> : <App />;
}
