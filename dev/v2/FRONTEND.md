# v2 — Frontend

A separate **frontend container** built from `frontend/`, served by Nginx, proxying `/api` to the backend.

## Stack

- **Vite** + **React 18** + **TypeScript**
- **Tailwind CSS** + **shadcn/ui** (https://ui.shadcn.com/)
- **TanStack Query** for server state (jobs, history, wanted, settings)
- **TanStack Router** for client-side routing (file-based config or code-based — pick code-based for simplicity)
- **Zustand** for ephemeral client state (live job progress events from SSE)
- `next-themes`-style provider for light / dark / auto theme (auto follows `prefers-color-scheme`)

No state management framework beyond Zustand. No Redux. No SWR.

## Design

- **Palette**: black and white. Use shadcn's `neutral` preset. Accent colour: none (or a single subtle gray). Status indicators (running, queued, error) use icons + text, not coloured pills, to stay clean.
- **Layout**: persistent left sidebar with five links — Wanted, Queue, History, Logs, Settings. Top bar with theme toggle (sun/moon/auto) and logout button.
- **Typography**: shadcn defaults (Inter or system stack).

## Pages

### `/login`

- Two fields (username, password), one button, error toast on 401.
- On success, redirect to the URL in `?next=` or `/wanted`.

### `/wanted` (default after login)

- Header: search box, tabs `[All | Movies | Series]`, toggle "Only items with no subtitles in any language", language filter dropdown (multi-select of language codes derived from the union of `missing` across the page).
- Body: a table (shadcn `Table`) with columns: Title, Type, Missing langs (badges), Action.
- Each row shows a small icon next to the title when there's a queued/running job for that item (`active_job_id` not null). The icon is sourced from the global SSE store, so it updates in real time.
- Action column: a "Transcribe" button that opens a small popover (shadcn `Popover` or `Dialog`) to choose language + format, then `POST /api/jobs`.
- TanStack Query: `useQuery(['wanted', filters])` with `staleTime: 30_000`. Re-fetched on `jobs:done` events from the SSE store (so completed jobs disappear from the list if they satisfied their missing-subtitle entry).

### `/queue`

- Two stacked sections: "Running" and "Queued". Each card shows title (from `bazarr_cache` join), source ref, language, format, progress bar, current stage/message, cancel button.
- Cards rerender from the SSE store on every `progress` event.
- On `done` events, the card animates out and the History page's cache is invalidated.

### `/history`

- Filters: date range, language, source, status. Aggregate strip at the top: total cost (USD), total duration, count.
- Table: title, language, duration, cost, status, finished_at. Click a row → side panel with full detail (output path, error message if failed).

### `/logs`

- Filters: level, since, optional job filter.
- Table: ts, level (badge), job link, message. Virtualised if needed (>2k rows).

### `/settings`

- Sections: Bazarr (poll interval, track-no-subs toggle), Path mappings (editable list of pairs), Mistral (model name, fallback rate per minute), Defaults (language, output format), UI (default theme).
- Save button writes a `PATCH /api/settings` with only the changed fields.

## Live progress wiring

```ts
// hooks/useJobsStream.ts
import { useEffect } from "react";
import { useJobsStore } from "@/lib/jobsStore";

export function useJobsStream() {
  const apply = useJobsStore((s) => s.apply);
  useEffect(() => {
    const es = new EventSource("/api/jobs/stream", { withCredentials: true });
    es.addEventListener("progress", (e) => apply("progress", JSON.parse(e.data)));
    es.addEventListener("done",     (e) => apply("done",     JSON.parse(e.data)));
    es.addEventListener("new",      (e) => apply("new",      JSON.parse(e.data)));
    es.onerror = () => { /* let EventSource auto-reconnect */ };
    return () => es.close();
  }, [apply]);
}
```

Mounted once in the root layout. Components select narrow slices from the Zustand store and re-render only when their slice changes.

## Auth

- A small `AuthGate` component wraps the protected routes and calls `GET /api/auth/me` once at app boot. On 401, redirect to `/login?next=<current>`. On success, set a `user` context.
- Login page uses TanStack Query's `useMutation` to call `POST /api/auth/login` and writes the user to the auth context.
- Logout calls `POST /api/auth/logout`, clears the query cache, and pushes `/login`.

## Theming

- `ThemeProvider` keeps the user choice (`light` | `dark` | `auto`) in `localStorage` (default `auto`).
- On `auto`, react to `prefers-color-scheme` changes via `matchMedia`.
- Applies via `document.documentElement.classList.toggle("dark", isDark)`.

## Dev server

```ts
// vite.config.ts
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
        ws: false,
      },
    },
  },
});
```

In Compose dev mode the proxy target is `http://backend:8000`. SSE works through Vite's proxy because it forwards `text/event-stream` unbuffered.

## Production container

`frontend/Dockerfile`:

```dockerfile
# Build
FROM node:20-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build      # outputs to dist/

# Serve
FROM nginx:1.27-alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
```

`frontend/nginx.conf` (essentials):

```nginx
server {
  listen 80;
  server_name _;

  root /usr/share/nginx/html;
  index index.html;

  # SPA fallback for client routing
  location / {
    try_files $uri /index.html;
  }

  # Backend proxy
  location /api/ {
    proxy_pass http://backend:8000/api/;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;

    # SSE requirements
    proxy_buffering off;
    proxy_cache off;
    proxy_read_timeout 24h;
    proxy_send_timeout 24h;
    chunked_transfer_encoding on;
  }
}
```

## What to scaffold first

1. `npm create vite@latest frontend -- --template react-ts`
2. Add Tailwind per shadcn instructions.
3. `npx shadcn-ui@latest init` then add: `button`, `dialog`, `dropdown-menu`, `input`, `label`, `popover`, `select`, `sheet`, `table`, `tabs`, `toast`, `tooltip`, `switch`, `badge`, `progress`, `card`, `separator`, `sonner`.
4. Drop in TanStack Query + TanStack Router providers in `main.tsx`.
5. Stub out the five pages with placeholders, get auth + login working against the M1 backend.
6. Iterate page-by-page from M4 onward.
