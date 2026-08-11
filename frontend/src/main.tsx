import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { RootApplication } from "./RootApplication";
import "./styles.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <RootApplication />
  </StrictMode>,
);
