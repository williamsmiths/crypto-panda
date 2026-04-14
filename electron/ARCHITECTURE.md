# Electron UI Architecture

## Stack
- Electron (main + preload + renderer)
- Node.js child process bridge for Python scripts
- Local JSON storage for job history
- Local encrypted cache (obfuscated) for secret fields

## Structure
- `electron/main.js`: app shell, IPC, job queue, scheduler, health checks.
- `electron/preload.js`: secure bridge API exposed to renderer.
- `electron/error-codes.js`: centralized Error Code constants.
- `electron/renderer/index.html`: tab layout.
- `electron/renderer/renderer.js`: UI logic and state handling.
- `electron/renderer/styles.css`: layout styling.

## Key flows
1. Renderer calls IPC `job:run`.
2. Main enqueues task, runs Python script, streams logs through `job-log`.
3. Completion event `job-done` updates history and dashboard.
4. Results tab reads artifacts from `../logs`.
5. Health tab runs API/DB/SMTP checks and returns Error Code on failure.

