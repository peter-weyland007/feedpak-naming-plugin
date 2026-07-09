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
PACKAGE_SUFFIXES = (".feedpak", ".sloppak")
DEFAULT_TEMPLATE = "{artist}_{title}.feedpak"
DUPLICATE_HANDLING_STOP = "stop"
DUPLICATE_HANDLING_AUTO_NUMBER = "auto_number"
DUPLICATE_HANDLING_SKIP_CONFLICTS = "skip_conflicts"
VALID_DUPLICATE_HANDLING = {
    DUPLICATE_HANDLING_STOP,
    DUPLICATE_HANDLING_AUTO_NUMBER,
    DUPLICATE_HANDLING_SKIP_CONFLICTS,
}
DEFAULT_PRESETS = [
    {"name": "Artist - Title", "template": "{artist}_{title}.feedpak"},
    {"name": "Title - Artist", "template": "{title}_{artist}.feedpak"},
    {"name": "Artist / Title", "template": "{artist}/{title}.feedpak"},
    {"name": "Year - Artist - Title", "template": "{year}_{artist}_{title}.feedpak"},
]
SAFE_CHARS_RE = re.compile(r"[^A-Za-z0-9._()\-\[\] ]+")
WHITESPACE_RE = re.compile(r"\s+")
NUMBERED_NAME_RE = re.compile(r"^(.*) \((\d+)\)$")


def _scan_root(dlc: Path) -> Path:
    return dlc


def _iter_feedpaks(root: Path) -> list[Path]:
    if not root.exists():
        return []
    found: list[Path] = []
    for suffix in PACKAGE_SUFFIXES:
        found.extend(p for p in root.rglob(f"*{suffix}") if p.is_file())
    return sorted(found, key=lambda p: p.as_posix().lower())


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


def _next_numbered_relative_path(relative_path: str, occupied_relative_paths: set[str]) -> str:
    candidate = _safe_relative_path(relative_path)
    parent = candidate.parent
    stem = candidate.stem
    suffix = candidate.suffix
    match = NUMBERED_NAME_RE.match(stem)
    if match:
        base_stem = match.group(1)
        next_index = int(match.group(2)) + 1
    else:
        base_stem = stem
        next_index = 2

    while True:
        numbered_name = f"{base_stem} ({next_index}){suffix}"
        numbered_relative = (parent / numbered_name).as_posix() if str(parent) != "." else numbered_name
        if numbered_relative not in occupied_relative_paths:
            return numbered_relative
        next_index += 1


def _render_values(meta: dict[str, Any], source_path: Path) -> dict[str, str]:
    return {
        "artist": _sanitize_piece(meta.get("artist") or ""),
        "title": _sanitize_piece(meta.get("title") or ""),
        "album": _sanitize_piece(meta.get("album") or ""),
        "year": _sanitize_piece(meta.get("year") or ""),
        "input_name": _sanitize_piece(source_path.stem),
    }


def _normalize_duplicate_handling(raw: Any, legacy_auto_number_conflicts: bool = False) -> str:
    value = str(raw or "").strip().lower()
    if value in VALID_DUPLICATE_HANDLING:
        return value
    if legacy_auto_number_conflicts:
        return DUPLICATE_HANDLING_AUTO_NUMBER
    return DUPLICATE_HANDLING_STOP


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
    duplicate_handling = _normalize_duplicate_handling(
        raw.get("duplicate_handling"),
        legacy_auto_number_conflicts=bool(raw.get("auto_number_conflicts") is True),
    )
    return {
        "default_template": str(raw.get("default_template") or DEFAULT_TEMPLATE).strip() or DEFAULT_TEMPLATE,
        "auto_apply_after_import": bool(raw.get("auto_apply_after_import") is True),
        "auto_number_conflicts": duplicate_handling == DUPLICATE_HANDLING_AUTO_NUMBER,
        "duplicate_handling": duplicate_handling,
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


def _selected_for_item(item: dict[str, Any], explicit_selection: set[str] | None) -> bool:
    if not item["actionable"]:
        return False
    if explicit_selection is None:
        return True
    return item["current_relative_path"] in explicit_selection


def _annotate_items(
    items: list[dict[str, Any]],
    explicit_selection: set[str] | None,
    duplicate_handling: str = DUPLICATE_HANDLING_STOP,
) -> dict[str, Any]:
    selected_paths_that_will_be_vacated = {
        item["current_relative_path"]
        for item in items
        if _selected_for_item(item, explicit_selection) and item["actionable"]
    }

    if duplicate_handling == DUPLICATE_HANDLING_AUTO_NUMBER:
        occupied_relative_paths = {
            item["current_relative_path"]
            for item in items
            if item["current_relative_path"] not in selected_paths_that_will_be_vacated
        }
        reserved_relative_paths: set[str] = set()
        for item in items:
            item["auto_numbered_from"] = None
            if not _selected_for_item(item, explicit_selection):
                continue
            desired_relative_path = item["proposed_relative_path"]
            resolved_relative_path = desired_relative_path
            if resolved_relative_path in occupied_relative_paths or resolved_relative_path in reserved_relative_paths:
                resolved_relative_path = _next_numbered_relative_path(
                    desired_relative_path,
                    occupied_relative_paths | reserved_relative_paths,
                )
                item["auto_numbered_from"] = desired_relative_path
            item["proposed_relative_path"] = resolved_relative_path
            item["proposed_path"] = str(item["root"] / resolved_relative_path)
            item["target_exists"] = False
            reserved_relative_paths.add(resolved_relative_path)

    selected_target_counts: Counter[str] = Counter(
        item["proposed_relative_path"]
        for item in items
        if _selected_for_item(item, explicit_selection)
    )

    rename_count = 0
    unchanged_count = 0
    conflict_count = 0
    excluded_count = 0
    selected_count = 0

    for item in items:
        selected = _selected_for_item(item, explicit_selection)
        item["selected"] = selected
        item["selectable"] = bool(item["actionable"])
        status = "unchanged"
        error = None

        if not item["actionable"]:
            unchanged_count += 1
        elif not selected:
            status = "excluded"
            excluded_count += 1
        else:
            selected_count += 1
            if selected_target_counts[item["proposed_relative_path"]] > 1:
                status = "conflict"
                error = "Another selected file would get the same name."
                conflict_count += 1
            elif item["target_exists"] and item["proposed_relative_path"] not in selected_paths_that_will_be_vacated:
                status = "conflict"
                error = "A file with that name already exists."
                conflict_count += 1
            else:
                status = "rename"
                rename_count += 1

        item["status"] = status
        item["error"] = error

    return {
        "items": items,
        "rename_count": rename_count,
        "unchanged_count": unchanged_count,
        "conflict_count": conflict_count,
        "excluded_count": excluded_count,
        "selected_count": selected_count,
    }


def _preview_items(
    root: Path,
    extract_meta,
    template: str,
    selected_current_paths: set[str] | None = None,
    duplicate_handling: str = DUPLICATE_HANDLING_STOP,
) -> dict[str, Any]:
    files = _iter_feedpaks(root)
    items: list[dict[str, Any]] = []

    for path in files:
        raw = extract_meta(path) or {}
        proposed_relative = render_name(template, raw, path)
        proposed_path = root / proposed_relative
        rel_current = path.relative_to(root).as_posix()
        rel_proposed = proposed_path.relative_to(root).as_posix()
        items.append(
            {
                "root": root,
                "current_path": str(path),
                "current_relative_path": rel_current,
                "proposed_path": str(proposed_path),
                "proposed_relative_path": rel_proposed,
                "artist": raw.get("artist") or "",
                "title": raw.get("title") or path.stem,
                "album": raw.get("album") or "",
                "year": raw.get("year") or "",
                "actionable": rel_current != rel_proposed,
                "target_exists": proposed_path.exists() and proposed_path != path,
            }
        )

    normalized_duplicate_handling = _normalize_duplicate_handling(duplicate_handling)
    annotated = _annotate_items(items, selected_current_paths, duplicate_handling=normalized_duplicate_handling)
    for item in annotated["items"]:
        item.pop("root", None)
    return {
        "template": template,
        "root": str(root),
        "auto_number_conflicts": normalized_duplicate_handling == DUPLICATE_HANDLING_AUTO_NUMBER,
        "duplicate_handling": normalized_duplicate_handling,
        **annotated,
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
        raw_duplicate_handling = payload.get("duplicate_handling") if "duplicate_handling" in payload else None
        duplicate_handling = _normalize_duplicate_handling(
            raw_duplicate_handling,
            legacy_auto_number_conflicts=bool(payload.get("auto_number_conflicts") is True),
        )
        if raw_duplicate_handling is None and not bool(payload.get("auto_number_conflicts") is True):
            duplicate_handling = current.get("duplicate_handling") or DUPLICATE_HANDLING_STOP
        settings = _normalize_settings({
            "default_template": str(payload.get("default_template") or current["default_template"]).strip() or DEFAULT_TEMPLATE,
            "auto_apply_after_import": bool(payload.get("auto_apply_after_import") is True),
            "duplicate_handling": duplicate_handling,
            "auto_number_conflicts": duplicate_handling == DUPLICATE_HANDLING_AUTO_NUMBER,
            "presets": presets,
        })
        _save_settings(config_file, settings)
        return settings

    @router.get("/preview")
    def preview(template: str | None = None, duplicate_handling: str | None = None):
        dlc = _dlc_root()
        if not dlc or not dlc.exists():
            return JSONResponse({"error": "DLC directory not found"}, status_code=500)
        settings = _load_settings(config_file)
        chosen = str(template or settings["default_template"] or DEFAULT_TEMPLATE)
        chosen_duplicate_handling = _normalize_duplicate_handling(
            duplicate_handling,
            legacy_auto_number_conflicts=settings["duplicate_handling"] == DUPLICATE_HANDLING_AUTO_NUMBER,
        )
        root = _scan_root(dlc)
        return _preview_items(root, _meta, chosen, duplicate_handling=chosen_duplicate_handling)

    @router.post("/apply")
    def apply(payload: dict[str, Any] = Body(default={})):  # noqa: B008 - FastAPI dependency style
        dlc = _dlc_root()
        if not dlc or not dlc.exists():
            return JSONResponse({"error": "DLC directory not found"}, status_code=500)
        settings = _load_settings(config_file)
        raw_duplicate_handling = payload.get("duplicate_handling") if "duplicate_handling" in payload else None
        duplicate_handling = _normalize_duplicate_handling(
            raw_duplicate_handling,
            legacy_auto_number_conflicts=bool(payload.get("auto_number_conflicts") is True),
        )
        if raw_duplicate_handling is None and not bool(payload.get("auto_number_conflicts") is True):
            duplicate_handling = settings["duplicate_handling"]
        template = str(payload.get("template") or settings["default_template"] or DEFAULT_TEMPLATE)
        selected_raw = payload.get("selected_current_paths")
        selected_current_paths = {
            str(path).strip()
            for path in (selected_raw if isinstance(selected_raw, list) else [])
            if str(path).strip()
        } or None
        root = _scan_root(dlc)
        preview_data = _preview_items(
            root,
            _meta,
            template,
            selected_current_paths=selected_current_paths,
            duplicate_handling=duplicate_handling,
        )
        blockers = [item for item in preview_data["items"] if item["status"] == "conflict"]
        if blockers and duplicate_handling != DUPLICATE_HANDLING_SKIP_CONFLICTS:
            return JSONResponse(
                {
                    "error": "Preview has conflicts in the selected rows. Resolve them before applying.",
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
            try:
                proposed.parent.mkdir(parents=True, exist_ok=True)
                current.rename(proposed)
            except Exception as exc:
                return JSONResponse(
                    {
                        "error": f"Rename failed for {item['current_relative_path']}: {exc}",
                        "failed": {
                            "from": item["current_relative_path"],
                            "to": item["proposed_relative_path"],
                        },
                        "renamed_count": len(renamed),
                        "renamed": renamed,
                    },
                    status_code=500,
                )
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
            "duplicate_handling": duplicate_handling,
            "selected_count": preview_data["selected_count"],
            "renamed_count": len(renamed),
            "skipped_conflict_count": len(blockers) if duplicate_handling == DUPLICATE_HANDLING_SKIP_CONFLICTS else 0,
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
