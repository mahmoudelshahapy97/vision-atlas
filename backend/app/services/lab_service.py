# app/services/lab_service.py
"""Vision Lab configuration: support levels, sample inputs, the tabs a
project's lab page shows, and validation of a run's input files."""

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from fastapi.concurrency import run_in_threadpool

from app.services.model_service import model_service
from app.vision.core import PIPELINES, Pipeline
from app.vision.registry import manager

logger = logging.getLogger(__name__)

SAMPLES_DIR = Path(__file__).resolve().parents[1] / "vision" / "samples"

# Same codes as seed_data.json's support_levels and each project's lab.support.
SUPPORT_LEVELS = [
    {"code": "ready", "label": "Ready", "description": "A public model or proven algorithm does this task directly."},
    {"code": "zero_shot", "label": "Zero-shot", "description": "Works from text prompts without training; fine-tune for production accuracy."},
    {"code": "rules", "label": "Model + rules", "description": "Public models plus decision logic (angles, timers, zones)."},
    {"code": "classical", "label": "Classical CV", "description": "Proven OpenCV algorithms; no training needed."},
    {"code": "baseline", "label": "Baseline", "description": "Works on easy cases; harder cases need a specialized model."},
    {"code": "custom_model", "label": "Bring your model", "description": "Pipeline and preprocessing ready; upload weights trained on your data for predictions."},
]

# Which media kinds each slot kind accepts.
_SLOT_ACCEPTS = {"image": {"image"}, "images": {"image"}, "video": {"video"}, "media": {"image", "video"}}

FilesBySlot = Dict[str, List[Tuple[str, str]]]  # slot -> [(file name, media kind)]


class LabService:
    def list_pipelines(self) -> List[Dict[str, Any]]:
        return [p.public() for p in sorted(PIPELINES.values(), key=lambda p: p.title)]

    def resolve_sample(self, rel_path: str) -> Optional[Path]:
        """A sample file inside SAMPLES_DIR, or None for anything else
        (missing files and path traversal alike)."""
        src = (SAMPLES_DIR / rel_path).resolve()
        if SAMPLES_DIR.resolve() not in src.parents or not src.is_file():
            return None
        return src

    def _samples(self, lab: Dict[str, Any]) -> Dict[str, List[Dict[str, Any]]]:
        samples: Dict[str, List[Dict[str, Any]]] = {}
        for slot, files in (lab.get("samples") or {}).items():
            samples[slot] = []
            for f in files:
                if not (SAMPLES_DIR / f).exists():
                    continue
                item = {"name": Path(f).name, "path": f, "url": f"/api/lab/samples/{f}"}
                poster = Path(f).with_suffix(".poster.jpg")
                if (SAMPLES_DIR / poster).exists():
                    item["poster"] = f"/api/lab/samples/{poster.as_posix()}"
                samples[slot].append(item)
        return samples

    async def _pipeline_info(self, user_id: Optional[int], name: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        p = PIPELINES[name]
        d = p.public()
        d["defaults"] = params or {}
        d["custom_models"] = await model_service.usable_for_task(user_id, p.custom_task)
        specs = await run_in_threadpool(manager.specs)  # cached after the first answer from models-serve
        d["model_specs"] = [
            {"key": k, "name": specs[k]["name"], "license": specs[k]["license"], "source": specs[k]["source"]}
            for k in p.models
            if k in specs
        ]
        return d

    def has_lab(self, project: Dict[str, Any]) -> bool:
        lab = project.get("lab") or {}
        return bool(lab.get("pipeline")) and lab["pipeline"] in PIPELINES

    async def project_lab(self, project: Dict[str, Any], user_id: Optional[int]) -> Dict[str, Any]:
        """The lab page for a project (from project_service.get_lab_context):
        main pipeline tab with the project's defaults, then its alternatives."""
        lab = project["lab"]
        tabs = [{"label": PIPELINES[lab["pipeline"]].title,
                 **await self._pipeline_info(user_id, lab["pipeline"], lab.get("params"))}]
        for alt in lab.get("alternatives") or []:
            if alt in PIPELINES:
                tabs.append({"label": PIPELINES[alt].title, **await self._pipeline_info(user_id, alt)})
        level = next((s for s in SUPPORT_LEVELS if s["code"] == lab.get("support")), SUPPORT_LEVELS[0])
        return {
            "project": {"id": project["id"], "title": project["title"], "description": project["description"],
                        "domain": project["domain_name"], "metric": project["task_metric"],
                        "caution": project["caution"]},
            "support": level,
            "note": lab.get("note"),
            "samples": self._samples(lab),
            "tabs": tabs,
        }

    def check_slots(self, pipe: Pipeline, files_by_slot: FilesBySlot) -> Optional[str]:
        """The message to show (422) when the files don't fit the pipeline's
        input slots, or None when they do."""
        for slot in pipe.slots:
            got = files_by_slot.get(slot.name, [])
            need_min = 0 if slot.optional else slot.min
            if len(got) < need_min:
                return f"Add {'at least ' + str(slot.min) + ' files' if slot.max > 1 else 'a file'} for '{slot.label}'."
            if len(got) > slot.max:
                return f"'{slot.label}' takes at most {slot.max} file{'s' if slot.max > 1 else ''}."
            allowed = _SLOT_ACCEPTS[slot.kind]
            for name, kind in got:
                if kind not in allowed:
                    return f"{name} isn't a supported {' or '.join(sorted(allowed))} file for '{slot.label}'."
        unknown = set(files_by_slot) - {s.name for s in pipe.slots}
        if unknown:
            return f"Unexpected file field(s): {', '.join(sorted(unknown))}."
        return None


lab_service = LabService()
