import { webDarkTheme, webLightTheme, type Theme } from '@fluentui/react-components';

export type ColorSchemeName = 'light' | 'dark';

export const THEMES: Record<ColorSchemeName, Theme> = {
  light: webLightTheme,
  dark: webDarkTheme,
};

const STORAGE_KEY = 'llmDemo.colorScheme';

function prefersDark(): boolean {
  if (typeof window === 'undefined' || !window.matchMedia) {
    return false;
  }
  return window.matchMedia('(prefers-color-scheme: dark)').matches;
}

export function getStoredColorScheme(): ColorSchemeName {
  if (typeof window === 'undefined') {
    return 'light';
  }
  try {
    const stored = window.localStorage.getItem(STORAGE_KEY);
    if (stored === 'light' || stored === 'dark') {
      return stored;
    }
  } catch {
    // localStorage unavailable (e.g. privacy mode) - fall through to system preference.
  }
  return prefersDark() ? 'dark' : 'light';
}

export function storeColorScheme(scheme: ColorSchemeName): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, scheme);
  } catch {
    // Ignore write failures; the toggle still works for the current session.
  }
}
