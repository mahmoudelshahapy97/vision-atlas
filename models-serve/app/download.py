"""Download (and test-load) models ahead of time, so the first lab run is fast.

    python -m app.download            # the core set used by most labs
    python -m app.download --all      # every public model
    python -m app.download yolo26-pose sam2
"""
import sys

from .registry import SPECS, ModelError, manager

CORE = ["yolo26-detect", "yolo26-segment", "yolo26-pose", "yolo26-classify", "yolo26-obb", "yoloe26", "easyocr", "yunet", "sface"]


def main(argv: list[str]) -> int:
    keys = list(SPECS) if "--all" in argv else [a for a in argv if not a.startswith("-")] or CORE
    failed = 0
    for k in keys:
        if k not in SPECS:
            print(f"? unknown model '{k}'. Known: {', '.join(SPECS)}")
            failed += 1
            continue
        try:
            if k == "easyocr":
                manager.get(k, ("ar", "en"))
                manager.get(k, ("en",))
            else:
                manager.get(k)
            print(f"✓ {k}")
        except ModelError as e:
            print(f"✗ {k}: {e}")
            failed += 1
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
