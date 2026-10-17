# Vision Project Atlas

A full-stack platform for 90 computer vision projects, with a **YOLO26-powered
Vision Lab**. Every project can be run on your own images or video, or on a
built-in sample, straight from the browser. Results come back as annotated
images and videos, tables, charts, downloads, rendered LaTeX and a 3D
point-cloud viewer. You can also upload your own Ultralytics models, track
which projects you're planning, building or have finished, and edit the
catalog as an admin.

```
browser ──same origin──> web (Vite / nginx) ──proxy──> api ──> postgres
                                                        │
                                       lab thread pool ─┼─> atlas-data volume (uploads, run outputs, uploaded models)
                                                        │
                                          model calls ──┴─HTTP─> models (models-serve, CPU or GPU) ──> model-weights volume
```

| Tier | Directory | Stack |
|---|---|---|
| Console | [`frontend/`](frontend) | React 18, Vite, React Router, hand-written CSS, KaTeX |
| API + Vision Lab | [`backend/`](backend) | FastAPI, asyncpg, OpenCV: the 79 lab pipelines, no PyTorch |
| Model server | [`models-serve/`](models-serve) | FastAPI, PyTorch, Ultralytics YOLO26/YOLOE-26, SAM 2.1, EasyOCR, Real-ESRGAN, LaMa, MiDaS … |
| Database | [`database/`](database) | PostgreSQL 17: schema, catalog seed, reference queries |

Each directory has its own README with the detail: pipelines and the API are
in `backend/README.md`, the models and how to move them to a GPU server are in
`models-serve/README.md`.

---

## Run the whole thing

```bash
cp backend/.env.example backend/.env   # then set JWT_SECRET (see the comment in the file)
docker compose up --build
```

| Service | URL | Notes |
|---|---|---|
| Console | http://localhost:8080 | nginx serving the built SPA and proxying the API |
| API | http://localhost:8000 | `/docs` for Swagger, `/health` for status (including the model server) |
| Model server | internal only (`models:8500`) | not published; see `models-serve/README.md` |
| Postgres | localhost:5432 | `atlas` / `atlas` / `atlas` |

Sign in as the admin from `backend/.env` (`ADMIN_EMAIL` / `ADMIN_PASSWORD`),
then change the password. The first run of each lab downloads its model into
the model server. See `models-serve/README.md` to prefetch models, to use an
NVIDIA GPU on this host (`docker-compose.gpu.yml`), or to run the models on a
separate GPU server (`MODELS_URL` + `docker compose up -d --scale models=0`).

These are the same host ports lost-found publishes, so the two stacks can't
run at the same time unless one of them is stopped or remapped.

The schema is `database/schema.sql` and the catalog is `database/seed.sql`.
Postgres applies both on the first boot of an empty volume. There is no ORM
and no Alembic. `docker compose down -v` resets everything, including
downloaded models.

Before the model server existed, downloaded weights lived in the api's
`atlas-data` volume. To reuse them instead of downloading again, copy them once:
`docker run --rm -v vision-atlas_atlas-data:/a:ro -v vision-atlas_model-weights:/b alpine sh -c "mkdir -p /b/weights && cp -a /a/weights/. /b/weights/"`.

## Tests

```bash
docker compose up -d postgres models
docker compose run --rm --no-deps -v ./backend/tests:/app/tests -v ./database:/sql:ro -e SQL_DIR=/sql \
  api sh -c "pip install -q -r requirements-dev.txt && pytest -q"      # backend (add -m slow: every lab, end to end)
docker compose run --rm --no-deps -v ./models-serve/tests:/app/tests \
  models sh -c "pip install -q -r requirements-dev.txt && pytest -q"   # model server
cd frontend && npm run build                                          # console builds
```
