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

class TestResizeObserver implements ResizeObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
}

Object.defineProperty(globalThis, "ResizeObserver", {
  writable: true,
  value: TestResizeObserver,
});

Object.defineProperty(globalThis.HTMLElement.prototype, "scrollTo", {
  configurable: true,
  value: () => undefined,
});

Object.defineProperty(globalThis.HTMLElement.prototype, "scrollIntoView", {
  configurable: true,
  value: () => undefined,
});
