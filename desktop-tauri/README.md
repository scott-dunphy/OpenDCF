# OpenDCF Desktop (Tauri Prototype)

This is a thin desktop shell so OpenDCF runs like a native app on macOS/Windows.

For full architecture + troubleshooting notes, see `TAURI_REFERENCE.md`.

## Prerequisites

- Rust toolchain (`rustup` + `cargo`)
- Node.js 20+
- Python virtual environment at repo root (`.venv`) with OpenDCF deps installed

## First Run

From repo root:

```bash
cd desktop-tauri
npm install
npm run dev
```

What happens:
- Tauri starts a desktop window.
- `beforeDevCommand` runs `scripts/run-backend.mjs`, which starts FastAPI at `http://127.0.0.1:8011`.

If needed, you can override the port:

```bash
OPENDCF_DESKTOP_PORT=8020 npm run dev
```

## Build Installers

```bash
cd desktop-tauri
npm run build
```

Installer artifacts are generated under `desktop-tauri/src-tauri/target/release/bundle/`.
The build now runs `scripts/prepare-frontend.mjs`, which copies frontend assets to `desktop-tauri/dist` and rewrites `/frontend/...` paths for bundled desktop mode.

## Notes

- This is a prototype shell for UX testing.
- In packaged mode, the app attempts to auto-start backend from repo root `.venv`.
- If the app opens blank, rebuild so the patched desktop assets are included:

```bash
cd desktop-tauri
npm run build
```
- If your repo path changes, set `OPENDCF_REPO_ROOT` before launching:

```bash
OPENDCF_REPO_ROOT=/path/to/Project_Ares open desktop-tauri/src-tauri/target/release/bundle/macos/OpenDCF.app
```
- For true distribution-grade one-click installs, package/ship backend runtime with the app.
