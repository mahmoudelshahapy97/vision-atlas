# Frontend: Vision Project Atlas

The console for the catalog, the Vision Lab, models, run history, the
progress board and catalog admin. It uses **Vite + React 18 + react-router-dom 6**
with one hand-written stylesheet (`src/index.css`) and no UI kit. The only
extra library is KaTeX, for LaTeX results.

## Quick start

The backend must be running first (see `../backend/README.md`), or bring the
whole stack up with `docker compose up -d --build` from the repository root.

```bash
cd frontend
npm install
cp .env.example .env          # adjust VITE_API_TARGET if the API isn't on 127.0.0.1:8000
npm run dev
```

Open <http://localhost:5173>.

## The proxy, and why there is one

`vite.config.js` forwards `/api`, `/media`, `/health`, `/docs`, `/redoc` and
`/openapi.json` to the backend, so **the browser only ever makes same-origin
requests**:

- **No CORS.** The dev server's port doesn't need to be in the API's `CORS_ORIGINS`.
- **`<img>` and `<video>` just work.** Run outputs (`/media/runs/...`) and lab
  samples (`/api/lab/samples/...`) are plain files that the result pages load
  directly.

### In production

`Dockerfile` builds the bundle and serves it from nginx. `nginx.conf.template`
does what the dev proxy does, with the API address coming from `ATLAS_API_URL`
(compose sets `http://api:8000`). **Keep the two in step.** A path proxied in
dev but not in nginx is a 404 that only appears after a build.

Two settings there are not optional:

- `try_files $uri $uri/ /index.html`. This is a `BrowserRouter`, so a hard
  refresh on `/projects/12/lab` asks the server for a path that isn't on disk.
- `client_max_body_size 250m`. Lab inputs include videos (`MAX_UPLOAD_MB`,
  200 MB by default) and model weights. nginx's 1 MB default would reject
  them first.

## Routes

| Path | Page | Access |
|---|---|---|
| `/` | Catalog (search, filters, progress) | public |
| `/projects/:id` | Project drawer over the catalog | public |
| `/projects/:id/lab` | Vision Lab for a project | public; running needs sign-in |
| `/models` | Public models and your uploaded models | public; upload needs sign-in |
| `/runs`, `/runs/:publicId` | Your run history, one run | user |
| `/board` | Your progress board | user |
| `/login`, `/register` | Sign in, create account | public |
| `/admin`, `/admin/new`, `/admin/:id/edit` | Catalog admin | admin |

## Layout

```
src/
  main.jsx · App.jsx        providers (auth, toast) around the router
  api/
    client.js               fetch wrapper: bearer token, JSON, errors, mediaUrl()
    endpoints.js            one namespace per backend router: projects.list(), runs.create(), ...
  auth/                     AuthContext.jsx · tokenStore.js (localStorage "atlas.token") · roles.js
  routes/                   AppRouter.jsx (lazy pages) · RequireAuth.jsx
  layouts/                  AppLayout.jsx (top nav) · AuthLayout.jsx (sign-in column)
  hooks/                    useAsync · usePolling · useDebounced
  utils/                    constants.js (statuses, levels, support codes) · format.js
  components/               DataStates · StatusChips · Toast · ProjectCard · ProjectDrawer · ThemeToggle
    lab/                    ParamForm · CanvasEditor · ResultView · Chart · PointCloud
  pages/                    Catalog · Board · Login · Models · NotFound
    lab/ runs/ admin/       LabPage · RunList, RunDetail · ProjectList, ProjectForm
  index.css                 design tokens (light/dark), every component's styles
```

## Things worth knowing before changing this

- **Pages call `api/endpoints.js`, never `fetch`.** Paths are relative to
  `/api`. `useAsync` and `usePolling` pass `{ signal }` through, so a request
  is aborted when its page unmounts or its inputs change.
- **Polling uses `usePolling`.** That covers a run in progress (lab page, run
  page) and a model prefetch. The next request is scheduled after the previous
  response, and polling stops once `keepPolling(data)` is false.
- **The result view renders the backend's run contract.** `components/lab/ResultView.jsx`
  draws `summary`, `images`, `video`, `tables`, `chart`, `files`, `text`,
  `latex`, `points3d` and `notes` from `Ctx.result` in `backend/app/vision/core.py`.
  A new result kind needs both sides.
- **Drawn geometry is normalized** (0..1 of the image). `CanvasEditor` and the
  pipelines both rely on that.
- **Theme** is `system`, `light` or `dark`, stored as `atlas.theme`, and
  applied with `data-theme` on `<html>`. The tokens are at the top of `index.css`.

## Configuration

| Variable | Default | |
|---|---|---|
| `VITE_API_TARGET` | `http://127.0.0.1:8000` | where the dev/preview proxy sends API traffic |
| `VITE_PORT` / `VITE_PREVIEW_PORT` | `5173` / `4173` | |
| `VITE_API_URL` | empty | only for serving the console from another origin than the API |

## Scripts

| | |
|---|---|
| `npm run dev` | dev server with the proxy |
| `npm run build` | production bundle in `dist/` |
| `npm run preview` | serve `dist/` with the same proxy |
