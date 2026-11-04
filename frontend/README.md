# Frontend setup

This frontend is a Vite + React + TypeScript shell for the Azure LLM Serving Demo operator UI.

## Prerequisites

- Node.js 18+
- npm 9+

## Install

```bash
cd frontend
npm install
```

## Run locally

```bash
cd frontend
npm run dev
```

The app runs on Vite's default port. To point it at a backend API, set:

```bash
VITE_API_BASE_URL=http://localhost:8000
```

## Lint

```bash
cd frontend
npm run lint
```

## Unit tests

```bash
cd frontend
npm run test
```

## End-to-end smoke test

```bash
cd e2e
npm install
npx playwright install chromium
npm test
```

The Playwright config starts the frontend dev server automatically and currently includes a single
app-load smoke test. Scenario coverage for the user stories will be added later.
