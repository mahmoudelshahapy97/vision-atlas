# app/api/routes/run_router.py
"""Vision Lab runs: submit inputs, follow progress, history, delete."""

import json
import logging
import shutil
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Request, Response, UploadFile, status

from app.api.deps import get_current_user, is_admin
from app.core.config import config
from app.schemas.lab_schemas import RunResponse, RunSummary
from app.services.lab_service import FilesBySlot, lab_service
from app.services.media_service import media_service
from app.services.model_service import model_service
from app.services.project_service import project_service
from app.services.run_service import run_service
from app.utils.upload_utils import UploadTooLarge, media_kind, save_upload
from app.vision import runner
from app.vision.core import PIPELINES, UserError, resolve_params
from app.vision.registry import manager

logger = logging.getLogger(__name__)
router = APIRouter(tags=["vision lab"], prefix="/runs")


def _input_entry(public_id: str, slot: str, rel: str, name: str) -> Dict[str, Any]:
    return {"slot": slot, "path": rel, "name": name, "kind": media_kind(name), "url": f"/media/runs/{public_id}/{rel}"}


async def _check_model_choice(params: Dict[str, Any], pipe, user: Dict[str, Any]) -> None:
    """A `model` param must be an uploaded model the caller may use, of the
    task this pipeline loads. Registers its file with the model manager so the
    worker thread can load it without touching the database."""
    model = params.get("model")
    if not model:
        return
    if not (isinstance(model, str) and model.startswith("custom:") and model[7:].isdigit()):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Unknown model choice.")
    m = await model_service.visible_to(int(model[7:]), user["id"])
    if not m:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="That model doesn't exist or isn't shared with you.")
    if m["task"] != pipe.custom_task:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"This step needs a {pipe.custom_task} model; '{m['name']}' is a {m['task']} model.",
        )
    manager.register_custom(model, m["file_path"])


async def _stage_inputs(
    public_id: str, uploads: List[Tuple[str, UploadFile]], samples: Dict[str, List[Path]]
) -> List[Dict[str, Any]]:
    """Copy uploads and chosen samples into media/runs/<public_id>/in/ (the
    worker's scratch copy; create_run then uploads them to the object store)."""
    base = runner.run_dir(public_id)
    (base / "in").mkdir(parents=True, exist_ok=True)
    limit = config.max_upload_mb * 1024 * 1024
    inputs: List[Dict[str, Any]] = []
    for n, (slot, up) in enumerate(uploads):
        rel = f"in/{n:03d}-{slot}{Path(up.filename).suffix.lower()}"
        try:
            await save_upload(up, base / rel, limit)
        except UploadTooLarge:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"{up.filename} is larger than {config.max_upload_mb} MB.",
            )
        inputs.append(_input_entry(public_id, slot, rel, up.filename))
    k = len(inputs)
    for slot, paths in samples.items():
        for src in paths:
            rel = f"in/{k:03d}-{slot}-{src.name}"
            shutil.copyfile(src, base / rel)
            inputs.append(_input_entry(public_id, slot, rel, src.name))
            k += 1
    return inputs


@router.post("", response_model=RunResponse, status_code=status.HTTP_202_ACCEPTED)
async def create_run(request: Request, current_user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    """Multipart form: project_id (optional), pipeline (optional if project has a lab), params (JSON),
    samples (JSON {slot: [sample paths]}), and one file field per input slot (repeat the field for several files).

    The form is read raw because its file field names are the pipeline's slot names."""
    form = await request.form()
    project_id = int(form["project_id"]) if form.get("project_id") else None
    project = await project_service.get_lab_context(project_id) if project_id else None
    if project_id and not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"No project with id {project_id}.")
    lab = (project["lab"] or {}) if project else {}
    name = form.get("pipeline") or lab.get("pipeline")
    if not name or name not in PIPELINES:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Choose a pipeline to run.")
    pipe = PIPELINES[name]
    try:
        params = json.loads(form.get("params") or "{}")
        samples = json.loads(form.get("samples") or "{}")
    except json.JSONDecodeError:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="params and samples must be JSON.")
    if not isinstance(params, dict) or not isinstance(samples, dict):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="params and samples must be JSON objects.")
    await _check_model_choice(params, pipe, current_user)

    in_flight = await run_service.count_in_flight(current_user["id"])
    if in_flight >= config.max_runs_in_flight:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"You already have {in_flight} runs in progress. Wait for one to finish.",
        )

    uploads = [(k, v) for k, v in form.multi_items() if hasattr(v, "filename") and v.filename]
    files_by_slot: FilesBySlot = {}
    for slot, up in uploads:
        files_by_slot.setdefault(slot, []).append((up.filename, media_kind(up.filename) or "unknown"))
    sample_files: Dict[str, List[Path]] = {}
    for slot, paths in samples.items():
        for pth in paths if isinstance(paths, list) else []:
            src = lab_service.resolve_sample(pth) if isinstance(pth, str) else None
            if src is None:
                raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"Unknown sample '{pth}'.")
            sample_files.setdefault(slot, []).append(src)
            files_by_slot.setdefault(slot, []).append((src.name, media_kind(src.name) or "unknown"))
    problem = lab_service.check_slots(pipe, files_by_slot)
    if problem:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=problem)

    public_id = uuid.uuid4().hex
    try:
        inputs = await _stage_inputs(public_id, uploads, sample_files)
        try:
            merged = resolve_params(pipe, lab.get("params") if name == lab.get("pipeline") else None, params)
        except UserError as e:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))
        run = await run_service.create_run(public_id, current_user["id"], project_id, name, merged, inputs)
        # The worker still reads the local copies; they go when the run ends.
        await media_service.store_run_files(run["id"], run["inputs"], None)
        if any(i.get("key") for i in run["inputs"]):
            await run_service.set_inputs(run["id"], run["inputs"])
    except HTTPException:
        runner.delete_files(public_id)
        raise
    except Exception as e:
        runner.delete_files(public_id)
        await media_service.delete_run_files(public_id)
        logger.error("Error starting a %s run: %s", name, e, exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Could not start the run.")
    runner.submit(run["id"])
    return await media_service.sign_run(run)


async def _own_run(public_id: str, user: Dict[str, Any]) -> Dict[str, Any]:
    run = await run_service.get_by_public_id(public_id)
    if not run or (run["user_id"] != user["id"] and not is_admin(user)):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found.")
    return run


@router.get("/{public_id}", response_model=RunResponse)
async def get_run(public_id: str, current_user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    return await media_service.sign_run(await _own_run(public_id, current_user))


def _thumbnail(result: Dict[str, Any]) -> Optional[str]:
    if result.get("images"):
        return result["images"][0].get("url")
    return (result.get("video") or {}).get("poster")


@router.get("", response_model=List[RunSummary])
async def list_runs(
    project_id: Optional[int] = None, limit: int = 50, current_user: Dict[str, Any] = Depends(get_current_user)
) -> List[Dict[str, Any]]:
    try:
        rows = await run_service.list_for_user(current_user["id"], project_id or None, min(max(limit, 1), 200))
        await media_service.sign_runs(rows)
    except Exception as e:
        logger.error("Error listing runs: %s", e, exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Could not list your runs.")
    out = []
    for r in rows:
        result = r["result"] or {}
        out.append({**r, "summary": (result.get("summary") or [])[:4], "thumbnail": _thumbnail(result)})
    return out


@router.delete("/{public_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_run(public_id: str, current_user: Dict[str, Any] = Depends(get_current_user)) -> Response:
    run = await _own_run(public_id, current_user)
    if run["status"] in ("queued", "running"):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This run is still in progress.")
    try:
        runner.delete_files(run["public_id"])
        await media_service.delete_run_files(run["public_id"])
        await run_service.delete_run(run["id"])
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    except Exception as e:
        logger.error("Error deleting run %s: %s", public_id, e, exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Could not delete the run.")
