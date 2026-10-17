# app/core/config.py
"""models-serve configuration, loaded from environment variables and .env."""

from pathlib import Path
from typing import List

from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict

load_dotenv()

SERVE_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        protected_namespaces=(),
    )

    app_name: str = "Vision Atlas models-serve"
    app_version: str = "1.0.0"
    log_level: str = "INFO"
    log_format: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

    # Shared secret the API sends as "Authorization: Bearer <token>". Empty
    # turns the check off, which is only right when the port is not published
    # (the default compose keeps it on the internal network).
    models_token: str = ""

    # =========================================================================
    # MODELS
    # =========================================================================
    weights_dir: Path = SERVE_DIR / "models"  # downloaded public models and pushed custom models
    yolo_size: str = "n"  # YOLO26 size for the built-in models: n, s, m, l, x
    device: str = "cpu"  # "cpu", "cuda:0", "mps"
    allow_model_downloads: bool = True  # set false for air-gapped installs
    # Registry keys to load at startup so the first run doesn't wait. JSON list in .env.
    preload: List[str] = []

    # Tracking keeps one model instance per video being processed.
    track_session_ttl: int = 300  # seconds without a frame before a session is dropped
    max_track_sessions: int = 32


config = Settings()
