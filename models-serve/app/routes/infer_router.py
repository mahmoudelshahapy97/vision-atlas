# app/routes/infer_router.py
"""Inference. Every route is a plain `def`, so FastAPI runs it in its thread
pool; the per-model locks in the registry keep two requests from sharing a
model's internal state."""

import json
from typing import Any, Dict, List

import numpy as np
from fastapi import APIRouter, Depends, File, Form, Response, UploadFile, status

from app import ops
from app.codec import InputError, decode, npy, result_json
from app.core.security import require_token
from app.sessions import sessions

router = APIRouter(prefix="/v1", tags=["inference"], dependencies=[Depends(require_token)])


def _meta(raw: str) -> Dict[str, Any]:
    try:
        m = json.loads(raw or "{}")
    except ValueError as e:
        raise InputError(f"meta is not JSON: {e}") from e
    if not isinstance(m, dict):
        raise InputError("meta must be a JSON object.")
    return m


def _read(parts: List[UploadFile]) -> List[np.ndarray]:
    return [decode(p.file.read(), p.filename) for p in parts]


def _model(m: Dict[str, Any]) -> str:
    key = m.get("model")
    if not isinstance(key, str) or not key:
        raise InputError("meta.model is required.")
    ops.check_key(key)
    ops.ensure_custom(key, m.get("custom_sha"))
    return key


def _results(results, m: Dict[str, Any]) -> Dict[str, Any]:
    return {"results": [result_json(r, bool(m.get("mask_data"))) for r in results]}


@router.post("/predict")
def predict(meta: str = Form("{}"), image: List[UploadFile] = File(...)) -> Dict[str, Any]:
    m = _meta(meta)
    imgs = _read(image)
    return _results(ops.predict(_model(m), imgs if m.get("batch") else imgs[0], m.get("kwargs")), m)


@router.post("/yoloe")
def yoloe(meta: str = Form("{}"), image: List[UploadFile] = File(...)) -> Dict[str, Any]:
    m = _meta(meta)
    imgs = _read(image)
    return _results(ops.yoloe(m.get("prompts") or [], imgs if m.get("batch") else imgs[0], m.get("kwargs")), m)


@router.post("/track")
def track(meta: str = Form("{}"), image: UploadFile = File(...)) -> Dict[str, Any]:
    m = _meta(meta)
    key = _model(m)
    tracker = m.get("tracker") or "bytetrack.yaml"
    if tracker not in ops.TRACKERS:
        raise InputError(f"Unknown tracker '{tracker}'.")
    img = decode(image.file.read(), image.filename)
    s = sessions.get(str(m.get("session") or ""), key)
    with s.lock:
        r = s.model.track(img, persist=True, tracker=tracker, **ops.predict_kwargs(m.get("kwargs")))
    return _results(r, m)


@router.delete("/track/{session}", status_code=status.HTTP_204_NO_CONTENT)
def end_track(session: str) -> Response:
    sessions.drop(session)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/embed")
def embed(meta: str = Form("{}"), image: List[UploadFile] = File(...)) -> Response:
    m = _meta(meta)
    return npy(ops.embed(_model(m), _read(image)))


@router.post("/ocr")
def ocr(meta: str = Form("{}"), image: UploadFile = File(...)) -> Dict[str, Any]:
    m = _meta(meta)
    langs = [str(x) for x in (m.get("langs") or ["en"])]
    return {"items": ops.ocr(langs, decode(image.file.read(), image.filename), m.get("kwargs"))}


@router.post("/latex")
def latex(image: UploadFile = File(...)) -> Dict[str, Any]:
    return {"latex": ops.latex(decode(image.file.read(), image.filename))}


@router.post("/realesrgan")
def realesrgan(image: UploadFile = File(...)) -> Response:
    return npy(ops.realesrgan(decode(image.file.read(), image.filename)))


@router.post("/lama")
def lama(image: UploadFile = File(...), mask: UploadFile = File(...)) -> Response:
    return npy(ops.lama(decode(image.file.read(), image.filename), decode(mask.file.read(), mask.filename)))


@router.post("/colorize")
def colorize(image: UploadFile = File(...)) -> Response:
    return npy(ops.colorize(decode(image.file.read(), image.filename)))


@router.post("/depth")
def depth(image: UploadFile = File(...)) -> Response:
    return npy(ops.depth(decode(image.file.read(), image.filename)))
