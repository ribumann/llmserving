import '@testing-library/jest-dom/vitest';
import { cleanup } from '@testing-library/react';
import { afterEach } from 'vitest';

// jsdom doesn't implement ResizeObserver; Fluent's MessageBar (used by
// StatusMessage) observes its container to decide when to reflow, so tests
// need a no-op stand-in.
class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}

if (typeof window.ResizeObserver === 'undefined') {
  (window as unknown as { ResizeObserver: typeof ResizeObserver }).ResizeObserver =
    ResizeObserverStub as unknown as typeof ResizeObserver;
}

// jsdom doesn't implement matchMedia; App.tsx uses it to detect narrow
// viewports for the nav drawer's overlay/inline mode.
if (!window.matchMedia) {
  window.matchMedia = (query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => false,
  }) as unknown as MediaQueryList;
}

afterEach(() => {
  cleanup();
});
