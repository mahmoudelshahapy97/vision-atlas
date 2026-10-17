# models-serve: every Vision Lab model behind one HTTP API

The Atlas API runs the 79 lab pipelines: OpenCV, drawing, video decoding and encoding,
tables. Whenever a pipeline needs a model, it calls this service. That keeps the GPU,
PyTorch and all the weights in one process, which can run on the same host as the API
or on a GPU server of its own.

```
api (CPU) ── pipelines ── app/vision/registry.py ──HTTP :8500──> models-serve (CPU or GPU)
                            (Result look-alikes)                    YOLO26 · YOLOE-26 · SAM 2.1 · EasyOCR
                                                                    LaTeX-OCR · Real-ESRGAN · LaMa · MiDaS
                                                                    colorization · YuNet/SFace files
```

| Model | Endpoint |
|---|---|
| YOLO26 detect / segment / pose / classify / OBB, plate and PPE models, SAM 2.1, uploaded `.pt` | `POST /v1/predict` |
| YOLO26 tracking (ByteTrack, one session per video) | `POST /v1/track`, `DELETE /v1/track/{session}` |
| YOLOE-26 text prompts | `POST /v1/yoloe` |
| YOLO26-cls embeddings (similarity search) | `POST /v1/embed` |
| EasyOCR (Arabic + English) | `POST /v1/ocr` |
| LaTeX-OCR | `POST /v1/latex` |
| Real-ESRGAN, one tile per call | `POST /v1/realesrgan` |
| Big-LaMa | `POST /v1/lama` |
| ECCV16 colorization | `POST /v1/colorize` |
| MiDaS depth | `POST /v1/depth` |
| YuNet / SFace | `GET /v1/models/{key}/file`. The API copies these files once and runs them with OpenCV, because they're tiny and called once per face. |

Other routes:

- `GET /v1/models` lists the catalog, with whether each model is downloaded and loaded,
  and the device.
- `POST /v1/models/{key}/load` downloads a model (if needed) and loads it.
- `PUT|DELETE /v1/custom/{key}` and `POST /v1/custom/inspect` handle uploaded models.
- `GET /health` needs no token.

Every `/v1` route needs `Authorization: Bearer $MODELS_TOKEN` when the token is set.
Swagger is at `/docs`.

## Wire format

Requests are `multipart/form-data`: a `meta` JSON field and file parts. The API sends
video frames and photos as JPEG at quality 95. It sends what must stay exact (ESRGAN
tiles, LaMa image and mask, the colorization input, depth input) as `.npy`. Pickles are
refused.

- Prediction answers are JSON with `names`, `boxes`, `masks.xy`, `keypoints`, `probs`
  and `obb`. SAM's answers also include the bitmask `masks.data`.
- Array answers are `.npy`.
- Ultralytics keyword arguments are allow-listed: `conf`, `iou`, `imgsz`, `classes`,
  `max_det`, `points`, `labels` and `bboxes`. `device` comes from this server's settings.
- Errors:
  - `503 {"error": "model"}`: the model can't be downloaded or loaded. The message is
    shown to the user.
  - `400 {"error": "input"}`: the request is malformed.
  - `409 {"error": "custom_missing"}`: an uploaded model isn't here yet.

**Uploaded models** stay owned by the API, which keeps the database row and the file.
On the first run that uses one, the API sends its sha256. If the file isn't here, the
API gets a 409, `PUT`s the file and retries. Files are stored by hash in
`WEIGHTS_DIR/custom/`, so a restart doesn't trigger another upload.

**Tracking:** each video gets its own model instance on the server, because Ultralytics
keeps tracker state inside the model. A session is removed when the API's tracker
object is garbage-collected, or after `TRACK_SESSION_TTL` seconds without a frame.

## Running

### Next to the API (default)

The repository's `docker-compose.yml` runs this service as `models` on the compose
network, with no published port. `docker compose up --build` starts it along with
everything else.

- **GPU on the same host:** `docker compose -f docker-compose.yml -f docker-compose.gpu.yml up --build`
- **Prefetch weights:** `docker compose exec models python -m app.download` downloads
  the core set; add `--all` for everything.

### On its own GPU server

On the GPU host (it needs Docker and the NVIDIA Container Toolkit), copy this
`models-serve/` folder and run:

```bash
cp .env.example .env            # set MODELS_TOKEN; DEVICE=cuda:0
docker compose up -d --build    # publishes :8500
curl http://localhost:8500/health
```

On the app host:

```bash
# vision-atlas/.env  (read by compose for ${MODELS_URL})
MODELS_URL=http://<gpu-host>:8500
# vision-atlas/backend/.env
MODELS_TOKEN=<the same token>

docker compose up -d --scale models=0     # postgres, api, web; no local models container
```

Open port 8500 only to the app host (security group or firewall). The token is the
only other guard, and requests travel over plain HTTP, so keep both machines on a
private network or VPN.

### Without Docker

```bash
cd models-serve
python -m venv .venv && source .venv/bin/activate
pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu   # or cu124
pip install -r requirements-dev.txt
pip install --no-deps -r requirements-latex.txt && pip install "albumentations==1.4.24" "transformers>=4.40,<5" einops
uvicorn app.main:app --port 8500 --workers 1
```

Run **one worker**: the loaded models and tracking sessions live in that process.
Requests are handled in its thread pool, and the per-model locks stop two runs from
using one model's internal state at the same time.

## Settings

| Setting | Default | |
|---|---|---|
| `MODELS_TOKEN` | empty (no check) | required by the standalone compose file |
| `DEVICE` | `cpu` | `cuda:0`, `cuda:1`, `mps` |
| `YOLO_SIZE` | `n` | `s`, `m`, `l` and `x` are more accurate and slower |
| `WEIGHTS_DIR` | `models-serve/weights` (`/data/weights` in Docker) | |
| `ALLOW_MODEL_DOWNLOADS` | `true` | `false` for air-gapped servers (copy the weights into `WEIGHTS_DIR`) |
| `PRELOAD` | `[]` | e.g. `["yolo26-detect","yolo26-pose"]`, loaded in the background at startup |
| `TRACK_SESSION_TTL` / `MAX_TRACK_SESSIONS` | `300` / `32` | |

On the API side, `MODELS_URL`, `MODELS_TOKEN` and `MODELS_TIMEOUT` (600 s, because a
model's first use may download it) are set in `backend/.env`. `MODELS_URL` can also be
set in the root `.env` for compose.

## Performance notes

- Video tracking and per-frame detection send one request per processed frame. On the
  same host that adds a few milliseconds per frame. Across a 1 Gbit LAN, a 1280 px
  JPEG frame adds roughly 5–15 ms. Use the labs' "Process every Nth frame" setting on
  long videos.
- Real-ESRGAN goes tile by tile (256 px), so the run's progress bar keeps moving.
- The first request for a model downloads and loads it. To avoid that wait, set
  `PRELOAD` or use **Models → Prefetch** in the console.

## Tests

```bash
docker compose run --rm --no-deps -v ./models-serve/tests:/app/tests models \
  sh -c "pip install -q -r requirements-dev.txt && pytest -q"          # codec + API on yolo26n (CPU)
# add "-m slow" for YOLOE, SAM, OCR, Real-ESRGAN, LaMa, colorization, MiDaS
```
