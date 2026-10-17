"""Runs pipelines in a background thread pool and records progress and results in inference_run.

Pipelines are synchronous (OpenCV, PyTorch), so they run in worker threads. The
database is async (asyncpg on the API's event loop), so every write a worker
makes goes back to that loop through run_coroutine_threadsafe; the threads
never open their own connections.
"""
from __future__ import annotations

import asyncio
import logging
import shutil
import time
import traceback
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from typing import Any, Coroutine, Optional

from ..core.config import config
from ..services.run_service import run_service
from . import pipelines  # noqa: F401  (registers pipelines)
from .core import PIPELINES, Ctx, InputFile, UserError
from .registry import ModelError

log = logging.getLogger("atlas.runner")
_executor: Optional[ThreadPoolExecutor] = None
_loop: Optional[asyncio.AbstractEventLoop] = None


def start(loop: asyncio.AbstractEventLoop) -> None:
    """Called from the API lifespan with its running loop."""
    global _executor, _loop
    _loop = loop
    if _executor is None:
        _executor = ThreadPoolExecutor(max_workers=max(1, config.lab_workers), thread_name_prefix="lab")


def stop() -> None:
    """Stop taking work. Runs still executing finish in the background; queued
    ones are dropped and marked failed by recover_interrupted on the next start."""
    global _executor, _loop
    if _executor is not None:
        _executor.shutdown(wait=False, cancel_futures=True)
    _executor, _loop = None, None


def run_dir(public_id: str) -> Path:
    return config.media_dir / "runs" / public_id


def submit(run_id: int) -> None:
    if _executor is None:
        raise RuntimeError("Lab runner is not started.")
    _executor.submit(_execute, run_id)


def _on_loop(coro: Coroutine[Any, Any, Any], wait: bool = True) -> Any:
    """Run a coroutine on the API's loop from a worker thread."""
    loop = _loop
    if loop is None or loop.is_closed():
        coro.close()
        raise RuntimeError("The API event loop is not available.")
    fut: Future = asyncio.run_coroutine_threadsafe(coro, loop)
    if wait:
        return fut.result()
    fut.add_done_callback(lambda f: f.exception() and log.warning("Progress update failed: %s", f.exception()))
    return None


def _execute(run_id: int) -> None:
    try:
        run = _on_loop(run_service.mark_running(run_id))
    except Exception:
        log.error("Run %s could not be started:\n%s", run_id, traceback.format_exc())
        return
    if run is None:
        return
    pipe = PIPELINES.get(run["pipeline"])
    base = run_dir(run["public_id"])
    inputs = [InputFile(i["slot"], base / i["path"], i["name"], i["kind"]) for i in run["inputs"]]
    last = [0.0]

    def progress(p: float) -> None:
        now = time.time()
        if now - last[0] > 0.7:
            last[0] = now
            try:
                _on_loop(run_service.set_progress(run_id, round(p, 3)), wait=False)
            except RuntimeError:
                pass

    started = time.time()
    result, error = None, None
    try:
        if pipe is None:
            raise UserError(f"Unknown pipeline '{run['pipeline']}'.")
        ctx = Ctx(run["public_id"], inputs, dict(run["params"] or {}), base / "out", progress)
        pipe.fn(ctx)
        result, status = ctx.result, "done"
    except (UserError, ModelError) as e:
        status, error = "error", str(e)
    except Exception as e:  # unexpected: log the trace, show a short message
        log.error("Run %s (%s) failed:\n%s", run["public_id"], run["pipeline"], traceback.format_exc())
        status, error = "error", f"Processing failed: {type(e).__name__}: {e}"
    try:
        _on_loop(run_service.finish(run_id, status, result, error, int((time.time() - started) * 1000)))
    except Exception:
        log.error("Run %s finished but its result could not be saved:\n%s", run["public_id"], traceback.format_exc())


def delete_files(public_id: str) -> None:
    shutil.rmtree(run_dir(public_id), ignore_errors=True)
