import os

import pytest

# Weights: WEIGHTS_DIR, else models-serve/models (the same folder the server
# uses), so tests reuse what's downloaded instead of fetching yolo26n.pt again.
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
