from __future__ import annotations

import importlib.util
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient


PLUGIN_PATH = Path(__file__).resolve().parents[1] / "feedpak_naming" / "routes.py"
SPEC = importlib.util.spec_from_file_location("feedpak_naming_routes", PLUGIN_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_render_name_supports_nested_folders_safely():
    result = MODULE.render_name(
        "{artist}/{title}.feedpak",
        {"artist": "Paramore", "title": "Hallelujah"},
        Path("Paramore_Hallelujah_v1_DD_p.feedpak"),
    )
    assert result == "Paramore/Hallelujah.feedpak"


def test_apply_can_limit_changes_to_selected_preview_rows(tmp_path):
    dlc = tmp_path / "dlc"
    lib = dlc / "sloppak"
    lib.mkdir(parents=True)
    first = lib / "Paramore_Hallelujah_v1_DD_p.feedpak"
    second = lib / "Weezer_Hold-Me_v1_DD_p.feedpak"
    first.write_text("fake")
    second.write_text("fake")
    cfg = tmp_path / "config"
    cfg.mkdir()

    def fake_extract_meta(path: Path):
        if path.name.startswith("Paramore") or path.name == "Hallelujah.feedpak":
            return {"artist": "Paramore", "title": "Hallelujah"}
        return {"artist": "Weezer", "title": "Hold Me"}

    app = FastAPI()
    MODULE.setup(
        app,
        {
            "log": type("L", (), {"info": lambda *a, **k: None, "warning": lambda *a, **k: None})(),
            "config_dir": cfg,
            "get_dlc_dir": lambda: dlc,
            "extract_meta": fake_extract_meta,
        },
    )
    client = TestClient(app)

    preview = client.get("/api/plugins/feedpak_naming/preview", params={"template": "{artist}/{title}.feedpak"})
    assert preview.status_code == 200
    rows = preview.json()["items"]
    assert len(rows) == 2

    apply = client.post(
        "/api/plugins/feedpak_naming/apply",
        json={
            "template": "{artist}/{title}.feedpak",
            "selected_current_paths": ["Paramore_Hallelujah_v1_DD_p.feedpak"],
        },
    )
    assert apply.status_code == 200
    assert apply.json()["selected_count"] == 1
    assert apply.json()["renamed_count"] == 1
    assert (lib / "Paramore" / "Hallelujah.feedpak").exists()
    assert second.exists()


def test_selected_subset_can_resolve_duplicate_target_conflicts(tmp_path):
    dlc = tmp_path / "dlc"
    lib = dlc / "sloppak"
    lib.mkdir(parents=True)
    first = lib / "one.feedpak"
    second = lib / "two.feedpak"
    first.write_text("fake")
    second.write_text("fake")
    cfg = tmp_path / "config"
    cfg.mkdir()

    app = FastAPI()
    MODULE.setup(
        app,
        {
            "log": type("L", (), {"info": lambda *a, **k: None, "warning": lambda *a, **k: None})(),
            "config_dir": cfg,
            "get_dlc_dir": lambda: dlc,
            "extract_meta": lambda path: {"artist": "Same", "title": "Song"},
        },
    )
    client = TestClient(app)

    preview = client.get("/api/plugins/feedpak_naming/preview", params={"template": "{artist}_{title}.feedpak"})
    assert preview.status_code == 200
    data = preview.json()
    assert data["conflict_count"] == 2

    apply = client.post(
        "/api/plugins/feedpak_naming/apply",
        json={
            "template": "{artist}_{title}.feedpak",
            "selected_current_paths": ["one.feedpak"],
        },
    )
    assert apply.status_code == 200
    assert apply.json()["renamed_count"] == 1
    assert (lib / "Same_Song.feedpak").exists()
    assert second.exists()
