import { defineConfig, mergeConfig } from 'vitest/config';
import viteConfig from './vite.config';

export default mergeConfig(
  viteConfig,
  defineConfig({
    test: {
      globals: true,
      environment: 'jsdom',
      setupFiles: './tests/setup.ts',
      include: ['tests/**/*.test.ts', 'tests/**/*.test.tsx'],
      // Fluent's Table/Combobox/interaction-heavy pages involve several
      // sequential user-event + waitFor round-trips; the 5s default can be
      // too tight on a loaded CI/dev machine.
      testTimeout: 15000,
      coverage: {
        reporter: ['text', 'html'],
      },
      // tabster's CJS build uses a dynamic export pattern that Node's
      // cjs-module-lexer can't statically analyze, which breaks named
      // imports (e.g. `createTabster`) when the package is externalized.
      // Inlining it forces Vitest to transform it through Vite/esbuild,
      // which resolves named exports correctly.
      server: {
        deps: {
          inline: [/tabster/, /@fluentui\//],
        },
      },
    },
  }),
);
