import "@testing-library/jest-dom/vitest";
import { configure } from "@testing-library/dom";

configure({ asyncUtilTimeout: 20_000 });

Object.defineProperty(globalThis, "matchMedia", {
  writable: true,
  value: (query: string): MediaQueryList => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: () => undefined,
    removeListener: () => undefined,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
    dispatchEvent: () => false,
  }),
});
