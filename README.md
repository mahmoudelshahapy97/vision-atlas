# Vision Project Atlas

A full-stack platform for 90 computer vision projects, with a **YOLO26-powered
Vision Lab**. Every project can be run on your own images or video, or on a
built-in sample, straight from the browser. Results come back as annotated
images and videos, tables, charts, downloads, rendered LaTeX and a 3D
point-cloud viewer. You can also upload your own Ultralytics models, track
which projects you're planning, building or have finished, and edit the
catalog as an admin.

```
browser ──same origin──> web (Vite / nginx) ──proxy──> api ──> postgres (records + presigned links)
   │                                                    │
   │                                   lab thread pool ─┼─> minio, bucket "atlas" (run inputs and outputs)
   └──presigned links─────────────────────────────────> minio
                                                        ├─> atlas-data volume (uploaded models, lab scratch)
                                                        │
                                          model calls ──┴─HTTP─> models (models-serve, CPU or GPU) ──> models-serve/models/ (host folder)
```

| Tier | Directory | Stack |
|---|---|---|
| Console | [`frontend/`](frontend) | React 18, Vite, React Router, hand-written CSS, KaTeX |
| API + Vision Lab | [`backend/`](backend) | FastAPI, asyncpg, OpenCV: the 79 lab pipelines, no PyTorch |
| Model server | [`models-serve/`](models-serve) | FastAPI, PyTorch, Ultralytics YOLO26/YOLOE-26, SAM 2.1, EasyOCR, Real-ESRGAN, LaMa, MiDaS … |
| Database | [`database/`](database) | PostgreSQL 17: schema, catalog seed, reference queries |
| Object storage | `minio` service | MinIO: images, videos and documents of every lab run |

Each directory has its own README with the detail: pipelines and the API are
in `backend/README.md`, the models and how to move them to a GPU server are in
`models-serve/README.md`.

---

## Run the whole thing

```bash
cp backend/.env.example backend/.env   # then set JWT_SECRET (see the comment in the file)
cat > .env <<'ENV'                     # MinIO credentials, next to docker-compose.yml (git-ignored)
MINIO_ROOT_USER=atlas
MINIO_ROOT_PASSWORD=<at least 8 characters>
MINIO_PUBLIC_URL=http://localhost:9000  # where browsers reach MinIO: use this host's name or IP
ENV
docker compose up --build
```

| Service | URL | Notes |
|---|---|---|
| Console | http://localhost:8080 | nginx serving the built SPA and proxying the API |
| API | http://localhost:8000 | `/docs` for Swagger, `/health` for status (including the model server) |
| Model server | internal only (`models:8500`) | not published; see `models-serve/README.md` |
| Postgres | localhost:5432 | `atlas` / `atlas` / `atlas` |
| MinIO API | http://localhost:9000 | browsers load run files from here through presigned links |
| MinIO console | http://localhost:9001 | `MINIO_ROOT_USER` / `MINIO_ROOT_PASSWORD` from `.env` |

Sign in as the admin from `backend/.env` (`ADMIN_EMAIL` / `ADMIN_PASSWORD`),
then change the password. The first run of each lab downloads its model into
the model server. See `models-serve/README.md` to prefetch models, to use an
NVIDIA GPU on this host (`docker-compose.gpu.yml`), or to run the models on a
separate GPU server (`MODELS_URL` + `docker compose up -d --scale models=0`).

These are the same host ports lost-found publishes (MinIO included), so the two
stacks can't run at the same time unless one of them is stopped or remapped
(`MINIO_API_HOST_PORT` / `MINIO_CONSOLE_HOST_PORT` in `.env` move MinIO).

The schema is `database/schema.sql` and the catalog is `database/seed.sql`.
Postgres applies both on the first boot of an empty volume. There is no ORM
and no Alembic. `docker compose down -v` resets the database, uploads and
run outputs.

### Where files go

Every lab run's inputs and outputs (images, videos, CSV/JSON/text downloads)
are stored in MinIO under `runs/<public_id>/in/` and `runs/<public_id>/out/`
in the private bucket `atlas`. Postgres keeps one `media_object` row per file
with its object key and a presigned GET link (7 days by default,
`MINIO_URL_EXPIRE_HOURS`). The run's JSON carries the same key and link. The
API re-signs a link that is about to expire whenever it returns the run, so the
console always gets a working URL. Links are signed for `MINIO_PUBLIC_URL`, so
that must be an address the browser can reach.

Pipelines still work on local files: a run's folder in the `atlas-data` volume
is scratch space that is deleted once its files are in MinIO. If MinIO is down
when a run ends, the files stay there and are served at `/media/...`. Move
them, and any runs from before MinIO, with:

```bash
docker compose exec api python -m app.scripts.migrate_media_to_minio
```

Uploaded `.pt` model weights stay on the `atlas-data` volume.

Model weights are plain files in `models-serve/models/` (bind-mounted into the
`models` container, ignored by git), so they survive `down -v`. Delete files
there to re-download them. The container writes as root, so new files may need
`sudo chown -R $USER models-serve/models` before you can remove them by hand.

## Tests

```bash
docker compose up -d postgres models minio-init
docker compose run --rm --no-deps -v ./backend/tests:/app/tests -v ./database:/sql:ro -e SQL_DIR=/sql \
  -e MINIO_PUBLIC_URL=http://minio:9000 api sh -c "pip install -q -r requirements-dev.txt && pytest -q"      # backend (add -m slow: every lab, end to end)
docker compose run --rm --no-deps -v ./models-serve/tests:/app/tests \
  models sh -c "pip install -q -r requirements-dev.txt && pytest -q"   # model server
cd frontend && npm run build                                          # console builds
```
