from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Body
from fastapi.responses import JSONResponse

PLUGIN_ID = "feedpak_naming"
PACKAGE_SUFFIX = ".feedpak"
DEFAULT_TEMPLATE = "{artist}_{title}.feedpak"
DEFAULT_PRESETS = [
    {"name": "Artist - Title", "template": "{artist}_{title}.feedpak"},
    {"name": "Title - Artist", "template": "{title}_{artist}.feedpak"},
    {"name": "Artist / Title", "template": "{artist}/{title}.feedpak"},
    {"name": "Year - Artist - Title", "template": "{year}_{artist}_{title}.feedpak"},
]
SAFE_CHARS_RE = re.compile(r"[^A-Za-z0-9._()\-\[\] ]+")
WHITESPACE_RE = re.compile(r"\s+")


def _scan_root(dlc: Path) -> Path:
    sloppak = dlc / "sloppak"
    return sloppak if sloppak.exists() else dlc


def _iter_feedpaks(root: Path) -> list[Path]:
    if not root.exists():
        return []
    return sorted(
        [p for p in root.rglob(f"*{PACKAGE_SUFFIX}") if p.is_file()],
        key=lambda p: p.as_posix().lower(),
    )


def _sanitize_piece(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    text = SAFE_CHARS_RE.sub("-", text)
    text = WHITESPACE_RE.sub(" ", text)
    text = re.sub(r"-+", "-", text)
    return text.strip(" .-")


def _normalize_segment(value: str) -> str:
    segment = _sanitize_piece(value)
    if not segment or segment in {".", ".."}:
        return ""
    return segment


def _safe_relative_path(relative_path: str) -> Path:
    raw_parts = [part for part in str(relative_path or "").split("/") if part != ""]
    safe_parts = [_normalize_segment(part) for part in raw_parts]
    parts = [part for part in safe_parts if part]
    if not parts:
        parts = ["converted-song.feedpak"]
    last = parts[-1]
    if not last.lower().endswith(PACKAGE_SUFFIX):
        last += PACKAGE_SUFFIX
    if last == PACKAGE_SUFFIX:
        last = f"converted-song{PACKAGE_SUFFIX}"
    parts[-1] = last
    return Path(*parts)


def _render_values(meta: dict[str, Any], source_path: Path) -> dict[str, str]:
    return {
        "artist": _sanitize_piece(meta.get("artist") or ""),
        "title": _sanitize_piece(meta.get("title") or ""),
        "album": _sanitize_piece(meta.get("album") or ""),
        "year": _sanitize_piece(meta.get("year") or ""),
        "input_name": _sanitize_piece(source_path.stem),
    }


def render_name(template: str, meta: dict[str, Any], source_path: Path) -> str:
    chosen = (template or DEFAULT_TEMPLATE).strip()
    values = _render_values(meta, source_path)
    rendered = chosen
    for key, value in values.items():
        rendered = rendered.replace("{" + key + "}", value)
    rendered = rendered.replace("\\", "/")
    safe = _safe_relative_path(rendered)
    return safe.as_posix()


def _normalize_settings(raw: dict[str, Any]) -> dict[str, Any]:
    presets_raw = raw.get("presets")
    presets: list[Any] = presets_raw if isinstance(presets_raw, list) else list(DEFAULT_PRESETS)
    cleaned_presets: list[dict[str, str]] = []
    for item in presets:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "Preset").strip() or "Preset"
        template = str(item.get("template") or DEFAULT_TEMPLATE).strip() or DEFAULT_TEMPLATE
        cleaned_presets.append({"name": name, "template": template})
    if not cleaned_presets:
        cleaned_presets = list(DEFAULT_PRESETS)
    return {
        "default_template": str(raw.get("default_template") or DEFAULT_TEMPLATE).strip() or DEFAULT_TEMPLATE,
        "auto_apply_after_import": bool(raw.get("auto_apply_after_import") is True),
        "presets": cleaned_presets,
    }


def _load_settings(config_file: Path) -> dict[str, Any]:
    if not config_file.exists():
        return _normalize_settings({})
    try:
        raw = json.loads(config_file.read_text(encoding="utf-8"))
    except Exception:
        raw = {}
    return _normalize_settings(raw)


def _save_settings(config_file: Path, settings: dict[str, Any]) -> None:
    config_file.parent.mkdir(parents=True, exist_ok=True)
    config_file.write_text(json.dumps(settings, indent=2, sort_keys=True), encoding="utf-8")


def _preview_items(root: Path, extract_meta, template: str) -> dict[str, Any]:
    files = _iter_feedpaks(root)
    items: list[dict[str, Any]] = []
    proposed_counter: Counter[str] = Counter()

    for path in files:
        raw = extract_meta(path) or {}
        proposed_relative = render_name(template, raw, path)
        proposed_path = root / proposed_relative
        rel_current = path.relative_to(root).as_posix()
        rel_proposed = proposed_path.relative_to(root).as_posix()
        proposed_counter[rel_proposed] += 1
        items.append(
            {
                "current_path": str(path),
                "current_relative_path": rel_current,
                "proposed_path": str(proposed_path),
                "proposed_relative_path": rel_proposed,
                "artist": raw.get("artist") or "",
                "title": raw.get("title") or path.stem,
                "album": raw.get("album") or "",
                "year": raw.get("year") or "",
            }
        )

    rename_count = 0
    unchanged_count = 0
    conflict_count = 0
    for item in items:
        current = Path(item["current_path"])
        proposed = Path(item["proposed_path"])
        status = "rename"
        error = None
        if proposed == current:
            status = "unchanged"
            unchanged_count += 1
        elif proposed_counter[item["proposed_relative_path"]] > 1:
            status = "conflict"
            error = "Another file would get the same name."
            conflict_count += 1
        elif proposed.exists() and proposed != current:
            status = "conflict"
            error = "A file with that name already exists."
            conflict_count += 1
        else:
            rename_count += 1
        item["status"] = status
        item["error"] = error

    return {
        "template": template,
        "root": str(root),
        "items": items,
        "rename_count": rename_count,
        "unchanged_count": unchanged_count,
        "conflict_count": conflict_count,
    }


def setup(app, context):
    router = APIRouter(prefix="/api/plugins/feedpak_naming")
    log = context["log"]
    config_dir = Path(context["config_dir"])
    config_file = config_dir / f"{PLUGIN_ID}.json"

    def _dlc_root() -> Path | None:
        try:
            root = context["get_dlc_dir"]()
            return Path(root) if root else None
        except Exception:
            return None

    def _meta(path: Path) -> dict[str, Any]:
        try:
            return context["extract_meta"](path) or {}
        except Exception as exc:  # pragma: no cover - defensive plugin guard
            log.warning("feedpak_naming metadata failed for %s: %s", path, exc)
            return {}

    @router.get("/settings")
    def settings_get():
        return _load_settings(config_file)

    @router.post("/settings")
    def settings_post(payload: dict[str, Any] = Body(default={})):  # noqa: B008
        current = _load_settings(config_file)
        presets = payload.get("presets", current["presets"])
        settings = _normalize_settings({
            "default_template": str(payload.get("default_template") or current["default_template"]).strip() or DEFAULT_TEMPLATE,
            "auto_apply_after_import": bool(payload.get("auto_apply_after_import") is True),
            "presets": presets,
        })
        _save_settings(config_file, settings)
        return settings

    @router.get("/preview")
    def preview(template: str | None = None):
        dlc = _dlc_root()
        if not dlc or not dlc.exists():
            return JSONResponse({"error": "DLC directory not found"}, status_code=500)
        settings = _load_settings(config_file)
        chosen = str(template or settings["default_template"] or DEFAULT_TEMPLATE)
        root = _scan_root(dlc)
        return _preview_items(root, _meta, chosen)

    @router.post("/apply")
    def apply(payload: dict[str, Any] = Body(default={})):  # noqa: B008 - FastAPI dependency style
        dlc = _dlc_root()
        if not dlc or not dlc.exists():
            return JSONResponse({"error": "DLC directory not found"}, status_code=500)
        settings = _load_settings(config_file)
        template = str(payload.get("template") or settings["default_template"] or DEFAULT_TEMPLATE)
        root = _scan_root(dlc)
        preview_data = _preview_items(root, _meta, template)
        blockers = [item for item in preview_data["items"] if item["status"] == "conflict"]
        if blockers:
            return JSONResponse(
                {
                    "error": "Preview has conflicts. Resolve them before applying.",
                    "preview": preview_data,
                },
                status_code=409,
            )

        renamed: list[dict[str, str]] = []
        for item in preview_data["items"]:
            if item["status"] != "rename":
                continue
            current = Path(item["current_path"])
            proposed = Path(item["proposed_path"])
            proposed.parent.mkdir(parents=True, exist_ok=True)
            current.rename(proposed)
            renamed.append({"from": item["current_relative_path"], "to": item["proposed_relative_path"]})
            try:
                parent = current.parent
                while parent != root and parent.exists() and not any(parent.iterdir()):
                    parent.rmdir()
                    parent = parent.parent
            except Exception:
                pass

        return {
            "template": template,
            "renamed_count": len(renamed),
            "renamed": renamed,
        }

    @router.post("/run-default")
    def run_default():
        settings = _load_settings(config_file)
        if not settings["auto_apply_after_import"]:
            return {"enabled": False, "message": "Auto-apply after import is disabled."}
        return apply({"template": settings["default_template"]})

    app.include_router(router)
    log.info("feedpak_naming routes registered")
