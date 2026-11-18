# OpenDCF Tauri Reference

This file explains how the desktop app is wired so future changes are easier.

## What Tauri Is Doing Here

OpenDCF desktop is a Tauri shell around the existing web app + FastAPI backend.

- Frontend: existing SPA in `../frontend`
- Backend: existing FastAPI app in `../src/main.py`
- Desktop wrapper: `desktop-tauri/`

Tauri gives you a native window (`OpenDCF.app` on macOS) that loads the frontend and talks to the backend on localhost.

## Runtime Architecture

There are two modes:

1. Dev mode (`npm run dev`)
- Tauri loads `devUrl` from `src-tauri/tauri.conf.json` (currently `http://127.0.0.1:8011`).
- `beforeDevCommand` runs `scripts/run-backend.mjs`.
- That script starts FastAPI on port `8011` (or reuses it if already running).

2. Bundled mode (`npm run build`, then open app)
- Tauri packages static web assets from `frontendDist`.
- `beforeBuildCommand` runs `scripts/prepare-frontend.mjs`.
- That script copies `../frontend` into `desktop-tauri/dist/frontend` and rewrites `/frontend/...` paths in `index.html` to `./frontend/...` so assets load from a packaged app.
- Rust entrypoint (`src-tauri/src/main.rs`) tries to auto-start backend from repo root `.venv`.

## Key Files

- `src-tauri/tauri.conf.json`: build config (`beforeDevCommand`, `beforeBuildCommand`, `devUrl`, `frontendDist`)
- `scripts/run-backend.mjs`: backend startup for dev mode
- `scripts/prepare-frontend.mjs`: static asset prep for bundled mode
- `src-tauri/src/main.rs`: backend auto-start in packaged app
- `../frontend/app.js`: detects Tauri and uses `http://127.0.0.1:8011` for API/health

## Commands You’ll Use

From repo root:

```bash
cd desktop-tauri
npm install
npm run dev
```

Build app bundle:

```bash
cd desktop-tauri
npm run build
```

macOS app output:

`desktop-tauri/src-tauri/target/release/bundle/macos/OpenDCF.app`

## Reload Behavior

When frontend/backend code changes:

- For dev mode: stop and re-run `npm run dev` (or let backend reload if started with reload elsewhere).
- For bundled app: re-run `npm run build` so `dist/` is regenerated and app bundle is rebuilt.

## Common Issues + Fixes

1. Blank app window
- Cause: bundled assets not rebuilt or bad asset paths.
- Fix: `cd desktop-tauri && npm run build` (runs `prepare-frontend.mjs`).

2. Address already in use (port conflict)
- Cause: backend already running on 8011.
- Fix: `run-backend.mjs` now reuses a healthy backend. If needed, kill process on 8011 and retry.

3. Backend not found in bundled mode
- Cause: app can’t find repo root or `.venv`.
- Fix: set `OPENDCF_REPO_ROOT` before launching app, e.g.:
  `OPENDCF_REPO_ROOT=/path/to/Project_Ares open .../OpenDCF.app`

4. DMG bundling errors on macOS
- Current config targets `all` bundles, so macOS build should produce both `.app` and `.dmg`.
- If DMG generation fails on a machine, check macOS permissions/tooling and retry from Terminal.

## Version/Config Notes

- Desktop API port default: `8011`
- Override dev backend port:
  `OPENDCF_DESKTOP_PORT=8020 npm run dev`
- Bundle target currently set in `tauri.conf.json`:
  `"targets": "all"`

## How to Change It Safely

If you change API port:
1. Update `desktop-tauri/scripts/run-backend.mjs`
2. Update `desktop-tauri/src-tauri/tauri.conf.json` `devUrl`
3. Update `frontend/app.js` Tauri backend origin
4. Update `src-tauri/src/main.rs` backend spawn port

Keep these four in sync.
