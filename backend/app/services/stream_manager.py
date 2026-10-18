# app/services/stream_manager.py
"""One asyncio worker per running camera, plus the supervisor that keeps them
running (ported from lost-found).

Every blocking call (reading a frame, a model call to models-serve, JPEG
encoding) runs on a thread, so the event loop keeps serving HTTP while cameras
are processed. A camera's `enabled` column is the operator's intent: enabled
cameras in active workspaces are started at boot, and the supervisor restarts
a worker that died, errored or wedged, starts an enabled camera that has no
worker, and stops workers whose camera was disabled, deleted or whose
workspace was deactivated.

Live viewers (WebSocket, app/api/routes/camera_router.py) wait on the
worker's frame counter and get the latest annotated JPEG; one encode per
frame serves every viewer.
"""

import asyncio
import logging
import time
from collections import deque
from datetime import datetime, timezone
from typing import Any, Callable, Deque, Dict, List, Optional

import cv2
import numpy as np

from app.core.config import config
from app.services.metric_service import MinuteAccumulator
from app.services.rtsp_reader import FrameReader
from app.vision import live
from app.vision.core import fit
from app.vision.registry import ModelError, manager

logger = logging.getLogger(__name__)

# A connected worker that has analysed nothing for this multiple of the open
# timeout is wedged inside a blocking read and can't recover on its own.
STALL_TIMEOUT_MULTIPLIER = 3.0

STARTING = "starting"
RUNNING = "running"
RECONNECTING = "reconnecting"
ERROR = "error"
STOPPED = "stopped"


class LiveCapacityError(Exception):
    """config.max_live_cameras workers are already running."""


def encode_jpeg(img: np.ndarray, quality: int) -> bytes:
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, quality])
    if not ok:
        raise RuntimeError("Couldn't encode a frame")
    return buf.tobytes()


class CameraWorker:
    """Reads one camera, runs its live analyzer and publishes annotated frames."""

    def __init__(
        self, camera: Dict[str, Any], on_output: Optional[Callable] = None, on_metrics: Optional[Callable] = None
    ) -> None:
        self.camera = camera
        self.camera_id: int = camera["id"]
        self.workspace_id: int = camera["workspace_id"]
        self.name: str = camera["name"]
        self.pipeline: Optional[str] = camera["pipeline"]
        self.reader = FrameReader(camera["source_url"])
        self.analyzer: Optional[live.LiveAnalyzer] = None
        # Events go to on_output (event_service), each finished minute of
        # metrics to on_metrics (metric_service); both set by the manager.
        self._on_output = on_output
        self._on_metrics = on_metrics
        declared = live.LIVE_ANALYZERS[self.pipeline].metrics if self.pipeline in live.LIVE_ANALYZERS else {}
        self.minutes = MinuteAccumulator(declared)
        self._writes: set = set()

        self._task: Optional[asyncio.Task] = None
        self._stop = asyncio.Event()
        self._frame_ready = asyncio.Condition()
        self._min_interval = 1.0 / max(0.1, float(camera["target_fps"]))
        # True while a blocking read runs on a thread; releasing the capture
        # under it can crash OpenCV, so stop() leaves it alone then.
        self._reading = False

        self.state = STOPPED
        self.started_at: Optional[datetime] = None
        self.last_frame_at: Optional[datetime] = None
        self.seq = 0
        self.jpeg: Optional[bytes] = None
        self.raw: Optional[np.ndarray] = None
        self.frame_size: Optional[tuple] = None
        self.frames_processed = 0
        self.events_emitted = 0
        self.reconnects = 0
        self.last_error: Optional[str] = None
        self.connected = False
        self.fps = 0.0
        self.metrics: Dict[str, float] = {}
        self.recent_events: Deque[Dict[str, Any]] = deque(maxlen=20)
        self._last_progress_at = time.monotonic()
        self._last_processed_at: Optional[float] = None
        self._t0 = time.monotonic()

    # ---------------------------------------------------------------- control
    async def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._stop.clear()
        self.state = STARTING
        self.started_at = datetime.now(timezone.utc)
        self._last_progress_at = time.monotonic()
        self._task = asyncio.create_task(self._run(), name=f"camera-{self.camera_id}")
        logger.info("Worker started for camera %s (%s)", self.name, self.camera_id)

    async def stop(self) -> None:
        self._stop.set()
        if self._task:
            try:
                await asyncio.wait_for(self._task, timeout=15)
            except asyncio.TimeoutError:
                logger.warning("Worker %s did not stop in time; cancelling.", self.name)
                self._task.cancel()
            except asyncio.CancelledError:
                pass
        if not self._reading:
            await asyncio.to_thread(self.reader.release)
        await self._close_analyzer()
        if self._on_metrics and self.minutes.minute is not None:
            await self._write_metrics(self.minutes.flush())  # the minute in progress
        if self._writes:
            await asyncio.wait(set(self._writes), timeout=5)
        self.connected = False
        self.state = STOPPED
        async with self._frame_ready:
            self._frame_ready.notify_all()  # viewers notice the stop
        logger.info("Worker stopped for camera %s", self.name)

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    @property
    def stopping(self) -> bool:
        return self._stop.is_set()

    @property
    def seconds_since_progress(self) -> float:
        return time.monotonic() - self._last_progress_at

    def status(self) -> Dict[str, Any]:
        return {
            "state": self.state,
            "running": self.running,
            "connected": self.connected,
            "started_at": self.started_at,
            "last_frame_at": self.last_frame_at,
            "seconds_since_frame": round(self.seconds_since_progress, 1),
            "fps": round(self.fps, 2),
            "frame_size": self.frame_size,
            "frames_processed": self.frames_processed,
            "events_emitted": self.events_emitted,
            "reconnects": self.reconnects,
            "last_error": self.last_error,
            "metrics": self.metrics,
            "recent_events": list(self.recent_events),
        }

    async def wait_frame(self, after_seq: int, timeout: float) -> bool:
        """True once a frame newer than `after_seq` exists; False on timeout or stop."""
        async with self._frame_ready:
            try:
                await asyncio.wait_for(
                    self._frame_ready.wait_for(lambda: self.seq > after_seq or not self.running), timeout
                )
            except asyncio.TimeoutError:
                return False
        return self.seq > after_seq

    # ------------------------------------------------------------------- loop
    async def _run(self) -> None:
        """Task entrypoint. Nothing may escape here and end the task quietly:
        a worker that dies without saying why just stops watching its camera."""
        try:
            await self._loop()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            self.state = ERROR
            self.last_error = f"worker crashed: {e}"
            logger.error("Camera %s: worker crashed: %s", self.name, e, exc_info=True)
        finally:
            if self.state != ERROR:
                self.state = STOPPED
            self.connected = False

    async def _loop(self) -> None:
        if self.pipeline:
            try:
                self.analyzer = await asyncio.to_thread(live.build, self.pipeline, self.camera["params"] or {})
            except Exception as e:
                self.state = ERROR
                self.last_error = f"couldn't start the {self.pipeline} pipeline: {e}"
                logger.error("Camera %s: %s", self.name, self.last_error, exc_info=True)
                return

        attempt = 0
        while not self._stop.is_set():
            if not self.reader.is_open:
                self.state = RECONNECTING if attempt or self.frames_processed else STARTING
                if not await asyncio.to_thread(self.reader.open):
                    attempt += 1
                    self.reconnects += 1
                    self.connected = False
                    self.last_error = f"couldn't open the video source (attempt {attempt})"
                    await self._sleep_backoff(attempt)
                    continue
                attempt = 0
                self.connected = True
                self.state = RUNNING
                self.last_error = None
                self._last_progress_at = time.monotonic()

            cycle_start = time.monotonic()
            ok, frame = await asyncio.to_thread(self._blocking_read)
            if not ok:
                # Each failed read on a dead server blocks for ffmpeg's timeout,
                # so counting failures alone takes minutes.
                if self.seconds_since_progress > config.rtsp_open_timeout or self.reader.should_reconnect():
                    logger.warning("Camera %s: no frame for %.0fs, reconnecting.", self.name, self.seconds_since_progress)
                    await asyncio.to_thread(self.reader.release)
                    self.connected = False
                    self.reconnects += 1
                await asyncio.sleep(0.2)
                continue

            try:
                await self._process(frame)
            except asyncio.CancelledError:
                raise
            except ModelError as e:
                self.last_error = str(e)
                logger.warning("Camera %s: model error: %s", self.name, e)
                await asyncio.sleep(1.0)
            except Exception as e:
                self.last_error = str(e)
                logger.error("Camera %s processing error: %s", self.name, e, exc_info=True)

            elapsed = time.monotonic() - cycle_start
            if elapsed < self._min_interval:
                await asyncio.sleep(self._min_interval - elapsed)

        if not self._reading:
            await asyncio.to_thread(self.reader.release)

    def _blocking_read(self):
        self._reading = True
        try:
            return self.reader.read()
        finally:
            self._reading = False

    def _analyse(self, frame: np.ndarray) -> tuple:
        """Runs on a thread: downscale, analyse, encode."""
        frame = fit(frame, config.camera_max_side)
        t = time.monotonic() - self._t0
        out = self.analyzer.step(frame, t) if self.analyzer else live.view_only(frame, self.name)
        return frame, out, encode_jpeg(out.frame, config.stream_jpeg_quality)

    async def _process(self, frame: np.ndarray) -> None:
        now = time.monotonic()
        frame, out, jpeg = await asyncio.to_thread(self._analyse, frame)
        self.raw = frame
        self.frame_size = (int(frame.shape[1]), int(frame.shape[0]))
        self.last_frame_at = datetime.now(timezone.utc)
        self.frames_processed += 1
        self._last_progress_at = now
        self._tick_fps(now)
        self.state = RUNNING
        self.metrics = out.metrics
        if self.last_error and not self.last_error.startswith("couldn't open"):
            self.last_error = None
        async with self._frame_ready:
            self.jpeg = jpeg
            self.seq += 1
            self._frame_ready.notify_all()
        for ev in out.events:
            self.events_emitted += 1
            self.recent_events.appendleft(
                {"kind": ev.kind, "label": ev.label, "severity": ev.severity, "track_id": ev.track_id, "at": self.last_frame_at}
            )
        if self._on_output and out.events:
            try:
                await self._on_output(self, out, frame)
            except Exception as e:
                logger.error("Camera %s: couldn't record output: %s", self.name, e, exc_info=True)
        if self._on_metrics and out.metrics:
            finished = self.minutes.add(out.metrics, self.last_frame_at)
            if finished:  # written in the background: a slow database mustn't stall the picture
                task = asyncio.create_task(self._write_metrics(finished))
                self._writes.add(task)
                task.add_done_callback(self._writes.discard)

    async def _write_metrics(self, rows) -> None:
        try:
            await self._on_metrics(self.camera_id, rows)
        except Exception as e:
            logger.warning("Camera %s: couldn't write metrics: %s", self.name, e)

    def _tick_fps(self, now: float) -> None:
        if self._last_processed_at is not None:
            interval = now - self._last_processed_at
            if interval > 0:
                instant = 1.0 / interval
                self.fps = instant if self.fps == 0 else 0.8 * self.fps + 0.2 * instant
        self._last_processed_at = now

    async def _close_analyzer(self) -> None:
        if self.analyzer is not None:
            analyzer, self.analyzer = self.analyzer, None
            try:
                await asyncio.to_thread(analyzer.close)
            except Exception as e:
                logger.debug("Camera %s: closing the analyzer failed: %s", self.name, e)

    async def _sleep_backoff(self, attempt: int) -> None:
        delay = min(config.rtsp_reconnect_delay_base * (2 ** max(0, attempt - 1)), config.rtsp_reconnect_delay_max)
        try:
            await asyncio.wait_for(self._stop.wait(), timeout=delay)
        except asyncio.TimeoutError:
            pass


class StreamManager:
    """Owns the worker per camera and keeps the set in step with the database."""

    def __init__(self) -> None:
        self.workers: Dict[int, CameraWorker] = {}
        self._lock = asyncio.Lock()
        self._supervisor: Optional[asyncio.Task] = None
        self._restarts: Dict[int, int] = {}
        self._retry_after: Dict[int, float] = {}
        # Set at startup (app/main.py): events -> event_service, metrics -> metric_service.
        self.on_output: Optional[Callable] = None
        self.on_metrics: Optional[Callable] = None

    # -------------------------------------------------------------- lifecycle
    async def startup(self) -> None:
        await self.reconcile()
        if self._supervisor is None:
            self._supervisor = asyncio.create_task(self._supervise(), name="camera-supervisor")

    async def shutdown(self) -> None:
        if self._supervisor is not None:
            self._supervisor.cancel()
            try:
                await self._supervisor
            except asyncio.CancelledError:
                pass
            self._supervisor = None
        async with self._lock:
            workers = list(self.workers.values())
            self.workers.clear()
        await asyncio.gather(*(w.stop() for w in workers), return_exceptions=True)
        logger.info("All camera workers stopped.")

    @staticmethod
    def _prepare(camera: Dict[str, Any]) -> None:
        """Tell the model manager where an uploaded model's weights are (the
        engine never reads the database); camera_service adds model_path."""
        if camera.get("model_path"):
            manager.register_custom(camera["params"]["model"], camera["model_path"])

    async def start_camera(self, camera: Dict[str, Any]) -> Dict[str, Any]:
        async with self._lock:
            existing = self.workers.get(camera["id"])
            if existing and existing.running:
                return existing.status()
            if not existing and len(self.workers) >= config.max_live_cameras:
                raise LiveCapacityError(
                    f"{config.max_live_cameras} cameras are already live, the most this server runs (MAX_LIVE_CAMERAS)."
                )
            if existing:
                await existing.stop()
            self._prepare(camera)
            worker = CameraWorker(camera, self.on_output, self.on_metrics)
            self.workers[camera["id"]] = worker
            await worker.start()
            return worker.status()

    async def stop_camera(self, camera_id: int) -> bool:
        async with self._lock:
            worker = self.workers.pop(camera_id, None)
        self._restarts.pop(camera_id, None)
        self._retry_after.pop(camera_id, None)
        if worker is None:
            return False
        await worker.stop()
        return True

    async def restart_camera(self, camera_id: int) -> Optional[Dict[str, Any]]:
        """A fresh worker built from the current row (after an edit, or by the
        supervisor). A camera that is no longer enabled isn't brought back."""
        from app.services.camera_service import camera_service  # import cycle: camera_service uses the manager

        async with self._lock:
            worker = self.workers.pop(camera_id, None)
        if worker is not None:
            await worker.stop()
        camera = await camera_service.get_runnable(camera_id)
        if not camera:
            return None
        return await self.start_camera(camera)

    # ------------------------------------------------------------ supervision
    async def _supervise(self) -> None:
        while True:
            try:
                await asyncio.sleep(max(1.0, config.worker_supervision_interval_s))
                await self.check_workers()
                await self.reconcile()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Camera supervisor iteration failed")

    @staticmethod
    def unhealthy_reason(worker: CameraWorker, stall_after: float) -> Optional[str]:
        if worker.stopping:
            return None
        if not worker.running:
            return f"worker is not running ({worker.last_error or 'exited'})"
        if worker.state == ERROR:
            return f"worker is in error state ({worker.last_error})"
        if worker.state == RUNNING and worker.connected and worker.seconds_since_progress > stall_after:
            return f"no frame analysed for {worker.seconds_since_progress:.0f}s"
        return None

    def _next_backoff(self, camera_id: int, now: float) -> int:
        attempt = self._restarts.get(camera_id, 0) + 1
        delay = min(config.worker_restart_backoff_base_s * (2 ** (attempt - 1)), config.worker_restart_backoff_max_s)
        self._restarts[camera_id] = attempt
        self._retry_after[camera_id] = now + delay
        return attempt

    async def check_workers(self) -> None:
        """Restart workers that died, errored or wedged, with exponential backoff."""
        now = time.monotonic()
        stall_after = config.rtsp_open_timeout * STALL_TIMEOUT_MULTIPLIER
        due: List[int] = []
        for camera_id, worker in list(self.workers.items()):
            reason = self.unhealthy_reason(worker, stall_after)
            if reason is None:
                if worker.state == RUNNING:
                    self._restarts.pop(camera_id, None)
                    self._retry_after.pop(camera_id, None)
                continue
            if now < self._retry_after.get(camera_id, 0.0):
                continue
            attempt = self._next_backoff(camera_id, now)
            logger.warning("Camera %s: %s -- restarting (attempt %s)", worker.name, reason, attempt)
            due.append(camera_id)
        results = await asyncio.gather(*(self.restart_camera(c) for c in due), return_exceptions=True)
        for camera_id, result in zip(due, results):
            if isinstance(result, Exception):
                logger.warning("Camera %s: restart failed: %s", camera_id, result)

    async def reconcile(self) -> None:
        """Workers for exactly the enabled cameras of active workspaces."""
        from app.services.camera_service import camera_service

        try:
            cameras = await camera_service.list_runnable()
        except Exception as e:
            logger.warning("Supervisor couldn't list cameras: %s", e)
            return
        wanted = {c["id"]: c for c in cameras}
        for camera_id in [c for c in self.workers if c not in wanted]:
            logger.info("Camera %s is no longer enabled; stopping its worker.", camera_id)
            await self.stop_camera(camera_id)
        now = time.monotonic()
        for camera_id, camera in wanted.items():
            if camera_id in self.workers or now < self._retry_after.get(camera_id, 0.0):
                continue
            try:
                await self.start_camera(camera)
            except LiveCapacityError as e:
                self._next_backoff(camera_id, now)
                logger.warning("Camera %s not started: %s", camera["name"], e)
            except Exception as e:
                self._next_backoff(camera_id, now)
                logger.warning("Camera %s: start failed: %s", camera["name"], e)

    # ------------------------------------------------------------------ query
    def get_worker(self, camera_id: int) -> Optional[CameraWorker]:
        return self.workers.get(camera_id)

    def status_of(self, camera_id: int) -> Dict[str, Any]:
        worker = self.workers.get(camera_id)
        if worker is None:
            return {"state": STOPPED, "running": False, "connected": False}
        return {**worker.status(), "supervisor_restarts": self._restarts.get(camera_id, 0)}


stream_manager = StreamManager()
