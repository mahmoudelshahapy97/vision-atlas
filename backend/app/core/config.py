# app/core/config.py
"""Central application configuration loaded from environment variables and .env."""

from pathlib import Path
from typing import List, Literal, Optional

from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict

load_dotenv()

BACKEND_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """
    Central application configuration.
    Loaded from:
    - Environment variables
    - .env
    - Defaults below
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        protected_namespaces=(),
    )

    # =========================================================================
    # APPLICATION
    # =========================================================================
    app_name: str = "Vision Project Atlas API"
    app_description: str = (
        "90 computer vision projects with a YOLO26-powered lab, per-user progress and run history."
    )
    app_version: str = "2.0.0"
    # Unversioned on purpose: the console and existing clients call /api/...
    app_api_prefix: str = "/api"
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    environment: Literal["development", "staging", "production"] = "development"

    # =========================================================================
    # CORS
    # =========================================================================
    # Only matters for the Vite dev server on another origin; in Docker the
    # console is same-origin through nginx. JSON list in .env.
    cors_origins: List[str] = ["http://localhost:5173", "http://localhost:8080"]
    cors_allow_credentials: bool = True
    cors_allow_methods: List[str] = ["*"]
    cors_allow_headers: List[str] = ["*"]

    # =========================================================================
    # AUTH
    # =========================================================================
    # No default: pydantic-settings refuses to build Settings without this set,
    # which is the right failure mode for a signing key. Generate one with:
    #   python -c "import secrets; print(secrets.token_urlsafe(48))"
    jwt_secret: str
    jwt_algorithm: str = "HS256"
    # Access tokens are short-lived; the console renews them with the refresh
    # token (rotated on every use, revocable: refresh_session).
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7

    # When both are set, this admin account is created on startup if it does
    # not exist yet -- see ensure_bootstrap_admin() in
    # app/services/user_service.py. An existing account is never changed.
    admin_email: Optional[str] = None
    admin_password: Optional[str] = None
    admin_name: str = "Admin"

    # =========================================================================
    # LOGGING
    # =========================================================================
    log_level: str = "INFO"
    log_format: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    # Empty string disables the file handler (console only).
    log_file_path: str = "logs/atlas.log"

    # =========================================================================
    # DATABASE
    # =========================================================================
    postgres_db: str = "atlas"
    postgres_user: str = "atlas"
    postgres_password: str = "atlas"
    db_host: str = "localhost"
    db_port: int = 5432

    db_min_pool_size: int = 2
    db_max_pool_size: int = 10
    db_timeout: float = 30.0
    db_command_timeout: float = 60.0
    db_max_retries: int = 10
    db_retry_delay_base: int = 2
    db_retry_delay_max: int = 30

    @property
    def database_dsn(self) -> str:
        return (
            f"postgresql://{self.postgres_user}:{self.postgres_password}"
            f"@{self.db_host}:{self.db_port}/{self.postgres_db}"
        )

    # =========================================================================
    # VISION LAB
    # =========================================================================
    media_dir: Path = BACKEND_DIR / "media"  # scratch for running labs; fallback storage when MinIO is off (served at /media)
    weights_dir: Path = BACKEND_DIR / "weights"  # uploaded model weights + YuNet/SFace copied from models-serve
    lab_workers: int = 2  # runs processed in parallel (one process, thread pool)
    max_upload_mb: int = 200
    max_video_seconds: int = 60  # longer videos are cut to this length
    max_runs_in_flight: int = 3  # per user (queued + running)

    # =========================================================================
    # MODEL SERVER (vision-atlas/models-serve)
    # =========================================================================
    # Every model runs there; DEVICE, YOLO_SIZE and ALLOW_MODEL_DOWNLOADS are
    # its settings now. Compose sets http://models:8500; point it at a GPU
    # host to split the stack.
    models_url: str = "http://localhost:8500"
    models_token: str = ""  # must match MODELS_TOKEN on models-serve
    models_timeout: float = 600.0  # seconds; a model's first use may download it


    # =========================================================================
    # OBJECT STORAGE (MinIO)
    # =========================================================================
    # Lab inputs and outputs (images, videos, documents) go to MinIO; Postgres
    # keeps each object's key and presigned link (media_object). Empty
    # endpoint: files stay under media_dir and are served at /media.
    minio_endpoint: str = ""  # host:port the API connects to (minio:9000 in compose)
    minio_access_key: str = ""
    minio_secret_key: str = ""
    minio_bucket: str = "atlas"
    minio_secure: bool = False
    # Where browsers reach MinIO; presigned links are signed for this host.
    # "/": same-origin links through the console's /<bucket>/ proxy.
    # Empty: the same as minio_endpoint.
    minio_public_url: str = ""
    minio_region: str = "us-east-1"  # fixed so signing never asks the server
    minio_url_expire_hours: int = 168  # presigned link lifetime; S3 allows at most 7 days

    # =========================================================================
    # CAMERAS (live pipelines; see app/services/stream_manager.py)
    # =========================================================================
    # Every live camera sends target_fps frames a second to models-serve, so
    # this cap is about the model server's capacity, not the API's.
    max_live_cameras: int = 8
    camera_files_dir: Path = Path("/data/camera-files")  # "file:<name>" sources; looped like a live stream
    rtsp_transport: str = "tcp"
    rtsp_open_timeout: float = 15.0  # seconds without a frame before a source counts as dead
    rtsp_read_failure_limit: int = 30
    rtsp_reconnect_delay_base: float = 2.0
    rtsp_reconnect_delay_max: float = 30.0
    camera_max_side: int = 1280  # frames are downscaled to this before analysis
    stream_jpeg_quality: int = 75
    live_token_minutes: int = 10  # lifetime of the token a browser opens a live view with
    worker_supervision_interval_s: float = 10.0
    worker_restart_backoff_base_s: float = 5.0
    worker_restart_backoff_max_s: float = 300.0
    event_retention_days: int = 30  # older camera events and their snapshots are deleted daily
    event_snapshot_quality: int = 85


config = Settings()
