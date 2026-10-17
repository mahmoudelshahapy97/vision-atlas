# app/core/logging_config.py
"""Console logging; the container runtime keeps the output."""

import logging

from app.core.config import config


def setup_logging() -> None:
    root = logging.getLogger()
    if root.handlers:
        return
    root.setLevel(getattr(logging, config.log_level.upper(), logging.INFO))
    console = logging.StreamHandler()
    console.setFormatter(logging.Formatter(config.log_format))
    root.addHandler(console)
    for noisy in ("ultralytics", "PIL", "urllib3", "matplotlib", "easyocr"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
