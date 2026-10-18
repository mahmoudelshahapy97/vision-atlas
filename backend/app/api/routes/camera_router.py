# app/api/routes/camera_router.py
"""Cameras in the active workspace (X-Workspace-Id), their live pipelines,
snapshots, and the live view over a WebSocket.

Roles: viewers watch; operators start and stop; workspace admins add, edit
and delete. The source URL's password is only shown to workspace admins.
"""

import asyncio
import logging
import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile, WebSocket, WebSocketDisconnect, status
from fastapi.concurrency import run_in_threadpool

from app.api.deps import require_workspace, workspace_access
from app.core.config import config
from app.core.security import create_media_token, decode_media_token
from app.schemas.camera_schemas import (
    CameraCreate,
    CameraResponse,
    CameraUpdate,
    LivePipelines,
    LiveToken,
    SourcePreview,
    VideoItem,
    VideoLibrary,
)
from app.services.camera_service import camera_service
from app.services.event_service import remove_camera_files
from app.services.model_service import model_service
from app.services.rtsp_reader import grab_single_frame
from app.services.stream_manager import LiveCapacityError, encode_jpeg, stream_manager
from app.services import video_library
from app.services.user_service import user_service
from app.utils import camera_sources
from app.utils.upload_utils import UploadTooLarge, save_upload
from app.vision import live
from app.vision.core import PIPELINES, UserError, fit

logger = logging.getLogger(__name__)
router = APIRouter(tags=["cameras"], prefix="/cameras")
ws_router = APIRouter(tags=["cameras"], prefix="/ws")

_NOT_FOUND = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Camera not found.")
LIVE_SCOPE = "camera.live"


def _out(camera: Dict[str, Any], role: str) -> Dict[str, Any]:
    shown = camera["source_url"] if role == "admin" else camera_sources.redact(camera["source_url"])
    return {**camera, "source_url": shown, "status": stream_manager.status_of(camera["id"])}


async def _camera(camera_id: int, access: Dict[str, Any]) -> Dict[str, Any]:
    camera = await camera_service.get(camera_id, access["workspace"]["id"])
    if not camera:
        raise _NOT_FOUND
    return camera


async def _check_source(source_url: str, workspace_id: int) -> str:
    try:
        return await run_in_threadpool(camera_sources.validate, source_url, workspace_id)
    except camera_sources.SourceError as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))


async def _check_pipeline(workspace: Dict[str, Any], pipeline: Optional[str], params: Dict[str, Any]) -> Dict[str, Any]:
    """The camera's settings, completed and coerced like a lab run's. An
    uploaded model must be shared with this workspace (or with everyone) and
    fit the pipeline's task, because the camera keeps using it for everyone."""
    if pipeline is None:
        return {}
    if pipeline not in live.LIVE_ANALYZERS:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"'{pipeline}' can't run on a live camera.")
    allowed = workspace["enabled_pipelines"]
    if allowed is not None and pipeline not in allowed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"This workspace isn't allowed the {PIPELINES[pipeline].title} pipeline. Ask a system admin.",
        )
    try:
        resolved = live.resolve(pipeline, params)
    except UserError as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))
    model = params.get("model")
    if model:
        task = PIPELINES[pipeline].custom_task
        m = await model_service.get_model(int(model[7:])) if isinstance(model, str) and model[7:].isdigit() else None
        if not m or not (m["is_public"] or m["workspace_id"] == workspace["id"]):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="A camera can only use models shared with this workspace or with everyone.",
            )
        if m["task"] != task:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"This pipeline needs a {task} model; '{m['name']}' is a {m['task']} model.",
            )
        resolved["model"] = model
    return resolved


# ------------------------------------------------------------------ catalogue

@router.get("/pipelines", response_model=LivePipelines)
async def live_pipelines(access: Dict[str, Any] = Depends(require_workspace("viewer"))) -> Dict[str, Any]:
    """What a camera here can run, in the lab's parameter-form shape, with the
    workspace's models that fit each one."""
    allowed = access["workspace"]["enabled_pipelines"]
    wid = access["workspace"]["id"]
    out = []
    for p in live.public_list():
        if allowed is not None and p["name"] not in allowed:
            continue
        task = p["custom_task"]
        p["custom_models"] = [
            m
            for m in await model_service.usable_for_task(access["user"]["id"], task)
            if m["public"] or m["workspace"] == access["workspace"]["name"]
        ] if task else []
        out.append(p)
    return {
        "pipelines": out,
        "samples": camera_sources.sample_videos(),
        "max_live_cameras": config.max_live_cameras,
        "live_now": len(stream_manager.workers),
    }


@router.post("/preview", responses={200: {"content": {"image/jpeg": {}}}})
async def preview_source(payload: SourcePreview, access: Dict[str, Any] = Depends(require_workspace("admin"))) -> Response:
    """One frame from a source before it is saved, to check it and draw zones on."""
    wid = access["workspace"]["id"]
    source = await _check_source(payload.source_url, wid)
    frame = await run_in_threadpool(grab_single_frame, source, 12.0, wid)
    if frame is None:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Couldn't read a frame from that source.")
    jpeg = await run_in_threadpool(lambda: encode_jpeg(fit(frame, config.camera_max_side), 85))
    return Response(jpeg, media_type="image/jpeg", headers={"Cache-Control": "no-store"})


# ------------------------------------------------------------- video library

def _video_out(v: Dict[str, Any], cameras: List[Dict[str, Any]]) -> Dict[str, Any]:
    sources = {v["file_source"], v.get("rtsp_url")}
    return {**v, "used_by": [c["name"] for c in cameras if c["source_url"] in sources]}


@router.get("/videos", response_model=VideoLibrary)
async def list_videos(access: Dict[str, Any] = Depends(require_workspace("viewer"))) -> Dict[str, Any]:
    """The workspace's uploaded recordings and the lab samples, each with the
    sources a camera can use: file:<name> and, with mediamtx, an RTSP URL."""
    wid = access["workspace"]["id"]
    cameras = await camera_service.list(wid)
    return {
        "rtsp_enabled": bool(config.mediamtx_url),
        "max_mb": config.max_camera_video_mb,
        "videos": [_video_out(v, cameras) for v in await run_in_threadpool(video_library.list_videos, wid)],
        "samples": [_video_out(v, cameras) for v in video_library.sample_streams()],
    }


@router.post("/videos", response_model=VideoItem, status_code=status.HTTP_201_CREATED)
async def upload_video(file: UploadFile = File(...), access: Dict[str, Any] = Depends(require_workspace("admin"))) -> Dict[str, Any]:
    """Add a recording to the library; it can then run as a looping camera."""
    wid = access["workspace"]["id"]
    folder = video_library.folder(wid)
    folder.mkdir(parents=True, exist_ok=True)
    try:
        taken = {p.name.lower() for p in folder.iterdir()}
        name = video_library.safe_name(file.filename, taken)
    except video_library.VideoError as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))
    final = folder / name
    partial = folder / f".{name}.part"  # hidden from the list (and from mediamtx) until checked
    try:
        await save_upload(file, partial, config.max_camera_video_mb * 1024 * 1024)
    except UploadTooLarge:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Videos larger than {config.max_camera_video_mb} MB aren't supported.",
        )
    if not await run_in_threadpool(video_library.is_video, partial):
        partial.unlink(missing_ok=True)
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="That file isn't a video we can play.")
    partial.rename(final)
    video = next(v for v in await run_in_threadpool(video_library.list_videos, wid) if v["name"] == name)
    return {**video, "used_by": []}


@router.delete("/videos/{name}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_video(name: str, access: Dict[str, Any] = Depends(require_workspace("admin"))) -> Response:
    wid = access["workspace"]["id"]
    try:
        path = video_library.path_of(wid, name)
    except video_library.VideoError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    if not path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such video.")
    video = next(v for v in await run_in_threadpool(video_library.list_videos, wid) if v["name"] == name)
    used = _video_out(video, await camera_service.list(wid))["used_by"]
    if used:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"{', '.join(used)} {'uses' if len(used) == 1 else 'use'} this video. Change or delete the camera first.",
        )
    path.unlink(missing_ok=True)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ------------------------------------------------------------------------ CRUD

@router.get("", response_model=List[CameraResponse])
async def list_cameras(access: Dict[str, Any] = Depends(require_workspace("viewer"))) -> List[Dict[str, Any]]:
    return [_out(c, access["role"]) for c in await camera_service.list(access["workspace"]["id"])]


@router.post("", response_model=CameraResponse, status_code=status.HTTP_201_CREATED)
async def create_camera(payload: CameraCreate, access: Dict[str, Any] = Depends(require_workspace("admin"))) -> Dict[str, Any]:
    ws = access["workspace"]
    if await camera_service.count(ws["id"]) >= ws["max_cameras"]:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"This workspace has its limit of {ws['max_cameras']} cameras. Ask a system admin to raise it.",
        )
    if await camera_service.name_taken(ws["id"], payload.name):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="A camera with this name already exists here.")
    fields = payload.model_dump()
    fields["source_url"] = await _check_source(payload.source_url, ws["id"])
    fields["params"] = await _check_pipeline(ws, payload.pipeline, payload.params)
    try:
        return _out(await camera_service.create(ws["id"], fields, access["user"]["id"]), access["role"])
    except Exception as e:
        logger.error("Error creating camera: %s", e, exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Could not create the camera.")


@router.get("/{camera_id}", response_model=CameraResponse)
async def get_camera(camera_id: int, access: Dict[str, Any] = Depends(require_workspace("viewer"))) -> Dict[str, Any]:
    return _out(await _camera(camera_id, access), access["role"])


@router.patch("/{camera_id}", response_model=CameraResponse)
async def update_camera(
    camera_id: int, payload: CameraUpdate, access: Dict[str, Any] = Depends(require_workspace("admin"))
) -> Dict[str, Any]:
    camera = await _camera(camera_id, access)
    fields = {k: v for k, v in payload.model_dump(exclude_unset=True).items() if v is not None or k in ("location", "pipeline")}
    if "name" in fields and await camera_service.name_taken(camera["workspace_id"], fields["name"], camera_id):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="A camera with this name already exists here.")
    if "source_url" in fields:
        fields["source_url"] = await _check_source(fields["source_url"], camera["workspace_id"])
    if "pipeline" in fields or "params" in fields:
        pipeline = fields.get("pipeline", camera["pipeline"])
        params = fields.get("params", camera["params"] if pipeline == camera["pipeline"] else {})
        fields["params"] = await _check_pipeline(access["workspace"], pipeline, params or {})
    updated = await camera_service.update(camera_id, fields)
    if stream_manager.get_worker(camera_id):
        try:
            await stream_manager.restart_camera(camera_id)
        except LiveCapacityError:
            pass
    return _out(updated, access["role"])


@router.delete("/{camera_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_camera(camera_id: int, access: Dict[str, Any] = Depends(require_workspace("admin"))) -> Response:
    await _camera(camera_id, access)
    await stream_manager.stop_camera(camera_id)
    await camera_service.delete(camera_id)  # its events and their media_object rows cascade
    await remove_camera_files(camera_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ------------------------------------------------------------------- running

@router.post("/{camera_id}/start", response_model=CameraResponse)
async def start_camera(camera_id: int, access: Dict[str, Any] = Depends(require_workspace("operator"))) -> Dict[str, Any]:
    """Runs the camera now and after every restart, until it is stopped."""
    camera = await _camera(camera_id, access)
    if not stream_manager.get_worker(camera_id) and len(stream_manager.workers) >= config.max_live_cameras:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"{config.max_live_cameras} cameras are already live, the most this server runs. Stop one first.",
        )
    await camera_service.set_enabled(camera_id, True)
    try:
        await stream_manager.restart_camera(camera_id)
    except LiveCapacityError as e:
        await camera_service.set_enabled(camera_id, False)
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    return _out({**camera, "enabled": True}, access["role"])


@router.post("/{camera_id}/stop", response_model=CameraResponse)
async def stop_camera(camera_id: int, access: Dict[str, Any] = Depends(require_workspace("operator"))) -> Dict[str, Any]:
    camera = await _camera(camera_id, access)
    await camera_service.set_enabled(camera_id, False)
    await stream_manager.stop_camera(camera_id)
    return _out({**camera, "enabled": False}, access["role"])


@router.get("/{camera_id}/snapshot", responses={200: {"content": {"image/jpeg": {}}}})
async def snapshot(
    camera_id: int,
    annotated: bool = False,
    access: Dict[str, Any] = Depends(require_workspace("viewer")),
) -> Response:
    """The latest frame of a running camera (annotated or raw), else one grabbed from the source."""
    camera = await _camera(camera_id, access)
    worker = stream_manager.get_worker(camera_id)
    if worker and annotated and worker.jpeg:
        jpeg = worker.jpeg
    elif worker and worker.raw is not None:
        jpeg = await run_in_threadpool(encode_jpeg, worker.raw, 88)
    else:
        frame = await run_in_threadpool(grab_single_frame, camera["source_url"], 12.0, camera["workspace_id"])
        if frame is None:
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Couldn't read a frame from this camera.")
        jpeg = await run_in_threadpool(lambda: encode_jpeg(fit(frame, config.camera_max_side), 88))
    return Response(jpeg, media_type="image/jpeg", headers={"Cache-Control": "no-store"})


@router.post("/{camera_id}/live-token", response_model=LiveToken)
async def live_token(camera_id: int, access: Dict[str, Any] = Depends(require_workspace("viewer"))) -> Dict[str, Any]:
    """A short-lived token for this camera's live WebSocket (browsers can't
    send an Authorization header when opening one)."""
    await _camera(camera_id, access)
    return {
        "token": create_media_token(access["user"]["id"], LIVE_SCOPE, camera_id, config.live_token_minutes),
        "expires_in": config.live_token_minutes * 60,
        "url": f"{config.app_api_prefix}/ws/cameras/{camera_id}",
    }


# ----------------------------------------------------------------- live view

async def _can_watch(user_id: int, camera_id: int) -> bool:
    user = await user_service.get_by_id(user_id)
    camera = await camera_service.get(camera_id)
    if not user or not user["is_active"] or not camera:
        return False
    try:
        await workspace_access(camera["workspace_id"], user, "viewer")
        return True
    except HTTPException:
        return False


@ws_router.websocket("/cameras/{camera_id}")
async def live_view(websocket: WebSocket, camera_id: int, token: str = Query(default="")) -> None:
    """The annotated live picture. Each frame is a JSON text message
    {"type": "frame", seq, width, height, fps, metrics, at} followed by the
    JPEG as one binary message. With no new frame for a few seconds a
    {"type": "status", state, error} message is sent instead, so the client
    can show why the picture stopped (stopped, reconnecting, error).

    The token only opens the connection; access is re-checked every minute,
    so removing someone from the workspace also closes their open views."""
    payload = decode_media_token(token, LIVE_SCOPE, camera_id)
    user_id = int(payload["sub"]) if payload else None
    if user_id is None or not await _can_watch(user_id, camera_id):
        await websocket.close(code=4403)
        return
    await websocket.accept()
    seq = 0
    checked = time.monotonic()
    try:
        while True:
            if time.monotonic() - checked > 60:
                if not await _can_watch(user_id, camera_id):
                    await websocket.close(code=4403)
                    return
                checked = time.monotonic()
            worker = stream_manager.get_worker(camera_id)
            if worker is None or not worker.running:
                await websocket.send_json({"type": "status", "state": "stopped", "error": worker.last_error if worker else None})
                await asyncio.sleep(2)
                continue
            if not await worker.wait_frame(seq, timeout=4):
                await websocket.send_json({"type": "status", "state": worker.state, "error": worker.last_error})
                continue
            seq = worker.seq
            jpeg = worker.jpeg
            await websocket.send_json(
                {
                    "type": "frame",
                    "seq": seq,
                    "width": worker.frame_size[0] if worker.frame_size else None,
                    "height": worker.frame_size[1] if worker.frame_size else None,
                    "fps": round(worker.fps, 1),
                    "metrics": worker.metrics,
                    "at": worker.last_frame_at.isoformat() if worker.last_frame_at else None,
                }
            )
            await websocket.send_bytes(jpeg)
    except (WebSocketDisconnect, RuntimeError):
        return
