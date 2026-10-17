import os
import tempfile
from pathlib import Path

import pytest

# Weights: reuse the container volume when there is one, so tests don't
# download yolo26n.pt every time.
os.environ.setdefault("WEIGHTS_DIR", "/data/weights" if Path("/data").is_dir() else str(Path(tempfile.gettempdir()) / "ms-weights"))
os.environ["MODELS_TOKEN"] = "test-token"
os.environ["DEVICE"] = os.environ.get("TEST_DEVICE", "cpu")
os.environ["PRELOAD"] = "[]"

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

AUTH = {"Authorization": "Bearer test-token"}


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="session")
def bus_jpg() -> bytes:
    from ultralytics.utils import ASSETS

    return (ASSETS / "bus.jpg").read_bytes()
