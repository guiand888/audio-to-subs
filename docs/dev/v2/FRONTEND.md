# Frontend

Separate **frontend container** built from `frontend/`, served by Nginx, proxying `/api` to the backend.

## Stack

- **Vite** + **React 18** + **TypeScript**
- **Tailwind CSS** + **shadcn/ui**
- **TanStack Query** for server state
- **TanStack Router** for client-side routing
- **Zustand** for ephemeral client state (live job progress)
- Light/dark/auto theme via `prefers-color-scheme`

## Pages

- `/login` - Auth with username/password
- `/wanted` - Bazarr items missing subtitles with filters
- `/queue` - Running and queued jobs with live progress
- `/history` - Completed jobs with aggregates
- `/logs` - Server-wide logs with filters
- `/settings` - Configuration management

## Live Progress

Global `EventSource('/api/jobs/stream')` mounted in root layout. Components select slices from Zustand store. Updates on progress/done/new events.

## Theming

Navy-brand ("Ayu Tint") palette. Theme provider keeps choice in localStorage, reacts to system preference changes.

## Production

Nginx serves static build with SSE-safe proxying: `proxy_buffering off`, `proxy_read_timeout 24h`.