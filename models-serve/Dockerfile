FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    PIP_NO_CACHE_DIR=1

# git: MiDaS sources are cloned on first use (and the CLIP requirement). libgl1/libglib: OpenCV.
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    git \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# CPU wheels by default; the GPU compose files switch this to a CUDA index.
ARG TORCH_INDEX=https://download.pytorch.org/whl/cpu
RUN pip install torch torchvision --index-url ${TORCH_INDEX}

COPY requirements.txt requirements-dev.txt requirements-latex.txt ./
RUN pip install -r requirements.txt \
    && pip install --no-deps -r requirements-latex.txt \
    && pip install "albumentations==1.4.24" "transformers>=4.40,<5" einops

COPY . .

# Downloaded and pushed weights live in /app/models; compose bind-mounts
# models-serve/models there, so they're plain files on the host.
ENV WEIGHTS_DIR=/app/models \
    NO_ALBUMENTATIONS_UPDATE=1 \
    YOLO_CONFIG_DIR=/app/models/.ultralytics
RUN mkdir -p /app/models
# LaTeX-OCR (pix2tex) always saves its checkpoints inside its own package.
# Point those two files at the volume so a rebuild doesn't drop 117 MB of weights.
RUN ck=$(python -c "import pix2tex, os; print(os.path.join(os.path.dirname(pix2tex.__file__), 'model', 'checkpoints'))") \
    && for f in weights.pth image_resizer.pth; do rm -f "$ck/$f" && ln -s "$WEIGHTS_DIR/pix2tex/$f" "$ck/$f"; done

EXPOSE 8500

HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8500/health || exit 1

# One worker on purpose: loaded models and tracking sessions live in this process.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8500", "--workers", "1", "--timeout-keep-alive", "300"]
