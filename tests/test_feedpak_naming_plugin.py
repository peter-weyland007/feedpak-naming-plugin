from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


PLUGIN_PATH = Path(__file__).resolve().parents[1] / "routes.py"
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


def test_preview_treats_case_only_path_differences_as_unchanged(tmp_path):
    dlc = tmp_path / "dlc"
    artist_dir = dlc / "Echo - the Bunnymen"
    artist_dir.mkdir(parents=True)
    song = artist_dir / "Lips Like Sugar.feedpak"
    song.write_text("fake")

    preview = MODULE._preview_items(
        dlc,
        lambda path: {"artist": "Echo - The Bunnymen", "title": "Lips Like Sugar"},
        "{artist}/{title}.feedpak",
    )

    row = preview["items"][0]
    assert row["current_relative_path"] == "Echo - the Bunnymen/Lips Like Sugar.feedpak"
    assert row["proposed_relative_path"] == "Echo - The Bunnymen/Lips Like Sugar.feedpak"
    assert row["status"] == "unchanged"
    assert preview["rename_count"] == 0
    assert preview["unchanged_count"] == 1


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
            "selected_current_paths": ["sloppak/Paramore_Hallelujah_v1_DD_p.feedpak"],
        },
    )
    assert apply.status_code == 200
    assert apply.json()["selected_count"] == 1
    assert apply.json()["renamed_count"] == 1
    assert (dlc / "Paramore" / "Hallelujah.feedpak").exists()
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
            "selected_current_paths": ["sloppak/one.feedpak"],
        },
    )
    assert apply.status_code == 200
    assert apply.json()["renamed_count"] == 1
    assert (dlc / "Same_Song.feedpak").exists()
    assert second.exists()


def test_preview_marks_conflict_when_selected_unchanged_row_already_occupies_target(tmp_path):
    dlc = tmp_path / "dlc"
    lib = dlc / "sloppak"
    lib.mkdir(parents=True)
    source = lib / "Children_Of_Bodom_Silent_Night_Bodom_Night_NA_DD.sloppak"
    source.write_text("fake")
    target_dir = dlc / "Children Of Bodom"
    target_dir.mkdir(parents=True)
    existing = target_dir / "Silent Night- Bodom Night.feedpak"
    existing.write_text("fake")
    cfg = tmp_path / "config"
    cfg.mkdir()

    app = FastAPI()
    MODULE.setup(
        app,
        {
            "log": type("L", (), {"info": lambda *a, **k: None, "warning": lambda *a, **k: None})(),
            "config_dir": cfg,
            "get_dlc_dir": lambda: dlc,
            "extract_meta": lambda path: {
                "artist": "Children Of Bodom",
                "title": "Silent Night- Bodom Night",
            },
        },
    )
    client = TestClient(app)

    apply = client.post(
        "/api/plugins/feedpak_naming/apply",
        json={
            "template": "{artist}/{title}.feedpak",
            "selected_current_paths": [
                "sloppak/Children_Of_Bodom_Silent_Night_Bodom_Night_NA_DD.sloppak",
                "Children Of Bodom/Silent Night- Bodom Night.feedpak",
            ],
        },
    )
    assert apply.status_code == 409
    body = apply.json()
    assert "Preview has conflicts" in body["error"]
    conflict_rows = [item for item in body["preview"]["items"] if item["status"] == "conflict"]
    assert len(conflict_rows) == 1
    assert conflict_rows[0]["current_relative_path"] == "sloppak/Children_Of_Bodom_Silent_Night_Bodom_Night_NA_DD.sloppak"


def test_preview_can_auto_number_conflicts_when_enabled(tmp_path):
    dlc = tmp_path / "dlc"
    lib = dlc / "sloppak"
    lib.mkdir(parents=True)
    source = lib / "Children_Of_Bodom_Silent_Night_Bodom_Night_NA_DD.sloppak"
    source.write_text("fake")
    target_dir = dlc / "Children Of Bodom"
    target_dir.mkdir(parents=True)
    existing = target_dir / "Silent Night- Bodom Night.feedpak"
    existing.write_text("already here")
    cfg = tmp_path / "config"
    cfg.mkdir()

    app = FastAPI()
    MODULE.setup(
        app,
        {
            "log": type("L", (), {"info": lambda *a, **k: None, "warning": lambda *a, **k: None})(),
            "config_dir": cfg,
            "get_dlc_dir": lambda: dlc,
            "extract_meta": lambda path: {
                "artist": "Children Of Bodom",
                "title": "Silent Night- Bodom Night",
            },
        },
    )
    client = TestClient(app)

    client.post(
        "/api/plugins/feedpak_naming/settings",
        json={"auto_number_conflicts": True},
    )
    preview = client.get("/api/plugins/feedpak_naming/preview", params={"template": "{artist}/{title}.feedpak"})
    assert preview.status_code == 200
    body = preview.json()
    row = next(item for item in body["items"] if item["current_relative_path"] == "sloppak/Children_Of_Bodom_Silent_Night_Bodom_Night_NA_DD.sloppak")
    assert row["status"] == "rename"
    assert row["proposed_relative_path"] == "Children Of Bodom/Silent Night- Bodom Night (2).feedpak"
    assert body["conflict_count"] == 0



def test_apply_can_auto_number_conflicts_when_enabled(tmp_path):
    dlc = tmp_path / "dlc"
    lib = dlc / "sloppak"
    lib.mkdir(parents=True)
    source = lib / "Children_Of_Bodom_Silent_Night_Bodom_Night_NA_DD.sloppak"
    source.write_text("fake")
    target_dir = dlc / "Children Of Bodom"
    target_dir.mkdir(parents=True)
    existing = target_dir / "Silent Night- Bodom Night.feedpak"
    existing.write_text("already here")
    cfg = tmp_path / "config"
    cfg.mkdir()

    app = FastAPI()
    MODULE.setup(
        app,
        {
            "log": type("L", (), {"info": lambda *a, **k: None, "warning": lambda *a, **k: None})(),
            "config_dir": cfg,
            "get_dlc_dir": lambda: dlc,
            "extract_meta": lambda path: {
                "artist": "Children Of Bodom",
                "title": "Silent Night- Bodom Night",
            },
        },
    )
    client = TestClient(app)

    client.post(
        "/api/plugins/feedpak_naming/settings",
        json={"auto_number_conflicts": True},
    )
    apply = client.post(
        "/api/plugins/feedpak_naming/apply",
        json={
            "template": "{artist}/{title}.feedpak",
            "selected_current_paths": ["sloppak/Children_Of_Bodom_Silent_Night_Bodom_Night_NA_DD.sloppak"],
        },
    )
    assert apply.status_code == 200
    body = apply.json()
    assert body["renamed_count"] == 1
    assert body["renamed"][0]["to"] == "Children Of Bodom/Silent Night- Bodom Night (2).feedpak"
    assert (dlc / "Children Of Bodom" / "Silent Night- Bodom Night (2).feedpak").exists()
    assert existing.exists()


def test_apply_can_skip_conflicting_rows_when_enabled(tmp_path):
    dlc = tmp_path / "dlc"
    lib = dlc / "sloppak"
    lib.mkdir(parents=True)
    conflict = lib / "conflict.feedpak"
    clean = lib / "clean.feedpak"
    conflict.write_text("fake")
    clean.write_text("fake")
    target_dir = dlc / "Children Of Bodom"
    target_dir.mkdir(parents=True)
    existing = target_dir / "Silent Night- Bodom Night.feedpak"
    existing.write_text("already here")
    cfg = tmp_path / "config"
    cfg.mkdir()

    def fake_extract_meta(path: Path):
        if path.name == "conflict.feedpak":
            return {"artist": "Children Of Bodom", "title": "Silent Night- Bodom Night"}
        return {"artist": "Paramore", "title": "Hallelujah"}

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

    saved = client.post(
        "/api/plugins/feedpak_naming/settings",
        json={"duplicate_handling": "skip_conflicts"},
    )
    assert saved.status_code == 200

    apply = client.post(
        "/api/plugins/feedpak_naming/apply",
        json={
            "template": "{artist}/{title}.feedpak",
            "selected_current_paths": [
                "sloppak/conflict.feedpak",
                "sloppak/clean.feedpak",
            ],
        },
    )
    assert apply.status_code == 200
    body = apply.json()
    assert body["duplicate_handling"] == "skip_conflicts"
    assert body["selected_count"] == 2
    assert body["renamed_count"] == 1
    assert body["skipped_conflict_count"] == 1
    assert body["renamed"][0]["to"] == "Paramore/Hallelujah.feedpak"
    assert (dlc / "Paramore" / "Hallelujah.feedpak").exists()
    assert conflict.exists()
    assert existing.exists()



def test_preview_uses_live_duplicate_handling_query_override(tmp_path):
    dlc = tmp_path / "dlc"
    lib = dlc / "sloppak"
    lib.mkdir(parents=True)
    source = lib / "Children_Of_Bodom_Silent_Night_Bodom_Night_NA_DD.sloppak"
    source.write_text("fake")
    target_dir = dlc / "Children Of Bodom"
    target_dir.mkdir(parents=True)
    existing = target_dir / "Silent Night- Bodom Night.feedpak"
    existing.write_text("already here")
    cfg = tmp_path / "config"
    cfg.mkdir()

    app = FastAPI()
    MODULE.setup(
        app,
        {
            "log": type("L", (), {"info": lambda *a, **k: None, "warning": lambda *a, **k: None})(),
            "config_dir": cfg,
            "get_dlc_dir": lambda: dlc,
            "extract_meta": lambda path: {
                "artist": "Children Of Bodom",
                "title": "Silent Night- Bodom Night",
            },
        },
    )
    client = TestClient(app)

    saved = client.post(
        "/api/plugins/feedpak_naming/settings",
        json={"duplicate_handling": "stop"},
    )
    assert saved.status_code == 200

    preview = client.get(
        "/api/plugins/feedpak_naming/preview",
        params={
            "template": "{artist}/{title}.feedpak",
            "duplicate_handling": "auto_number",
        },
    )
    assert preview.status_code == 200
    body = preview.json()
    row = next(item for item in body["items"] if item["current_relative_path"] == "sloppak/Children_Of_Bodom_Silent_Night_Bodom_Night_NA_DD.sloppak")
    assert body["duplicate_handling"] == "auto_number"
    assert row["status"] == "rename"
    assert row["proposed_relative_path"] == "Children Of Bodom/Silent Night- Bodom Night (2).feedpak"



def test_apply_uses_live_duplicate_handling_payload_override(tmp_path):
    dlc = tmp_path / "dlc"
    lib = dlc / "sloppak"
    lib.mkdir(parents=True)
    source = lib / "Children_Of_Bodom_Silent_Night_Bodom_Night_NA_DD.sloppak"
    source.write_text("fake")
    target_dir = dlc / "Children Of Bodom"
    target_dir.mkdir(parents=True)
    existing = target_dir / "Silent Night- Bodom Night.feedpak"
    existing.write_text("already here")
    cfg = tmp_path / "config"
    cfg.mkdir()

    app = FastAPI()
    MODULE.setup(
        app,
        {
            "log": type("L", (), {"info": lambda *a, **k: None, "warning": lambda *a, **k: None})(),
            "config_dir": cfg,
            "get_dlc_dir": lambda: dlc,
            "extract_meta": lambda path: {
                "artist": "Children Of Bodom",
                "title": "Silent Night- Bodom Night",
            },
        },
    )
    client = TestClient(app)

    saved = client.post(
        "/api/plugins/feedpak_naming/settings",
        json={"duplicate_handling": "stop"},
    )
    assert saved.status_code == 200

    apply = client.post(
        "/api/plugins/feedpak_naming/apply",
        json={
            "template": "{artist}/{title}.feedpak",
            "duplicate_handling": "auto_number",
            "selected_current_paths": ["sloppak/Children_Of_Bodom_Silent_Night_Bodom_Night_NA_DD.sloppak"],
        },
    )
    assert apply.status_code == 200
    body = apply.json()
    assert body["duplicate_handling"] == "auto_number"
    assert body["renamed_count"] == 1
    assert body["renamed"][0]["to"] == "Children Of Bodom/Silent Night- Bodom Night (2).feedpak"
    assert (dlc / "Children Of Bodom" / "Silent Night- Bodom Night (2).feedpak").exists()
    assert existing.exists()



def test_settings_round_trip_auto_number_conflicts_flag(tmp_path):
    dlc = tmp_path / "dlc"
    dlc.mkdir(parents=True)
    cfg = tmp_path / "config"
    cfg.mkdir()

    app = FastAPI()
    MODULE.setup(
        app,
        {
            "log": type("L", (), {"info": lambda *a, **k: None, "warning": lambda *a, **k: None})(),
            "config_dir": cfg,
            "get_dlc_dir": lambda: dlc,
            "extract_meta": lambda path: {},
        },
    )
    client = TestClient(app)

    saved = client.post(
        "/api/plugins/feedpak_naming/settings",
        json={"auto_number_conflicts": True},
    )
    assert saved.status_code == 200
    assert saved.json()["auto_number_conflicts"] is True
    assert saved.json()["duplicate_handling"] == "auto_number"

    loaded = client.get("/api/plugins/feedpak_naming/settings")
    assert loaded.status_code == 200
    assert loaded.json()["auto_number_conflicts"] is True
    assert loaded.json()["duplicate_handling"] == "auto_number"


def test_settings_round_trip_duplicate_handling_skip_conflicts(tmp_path):
    dlc = tmp_path / "dlc"
    dlc.mkdir(parents=True)
    cfg = tmp_path / "config"
    cfg.mkdir()

    app = FastAPI()
    MODULE.setup(
        app,
        {
            "log": type("L", (), {"info": lambda *a, **k: None, "warning": lambda *a, **k: None})(),
            "config_dir": cfg,
            "get_dlc_dir": lambda: dlc,
            "extract_meta": lambda path: {},
        },
    )
    client = TestClient(app)

    saved = client.post(
        "/api/plugins/feedpak_naming/settings",
        json={"duplicate_handling": "skip_conflicts"},
    )
    assert saved.status_code == 200
    assert saved.json()["duplicate_handling"] == "skip_conflicts"
    assert saved.json()["auto_number_conflicts"] is False

    loaded = client.get("/api/plugins/feedpak_naming/settings")
    assert loaded.status_code == 200
    assert loaded.json()["duplicate_handling"] == "skip_conflicts"
    assert loaded.json()["auto_number_conflicts"] is False



def test_settings_round_trip_include_builtin_content_flag(tmp_path):
    dlc = tmp_path / "dlc"
    dlc.mkdir(parents=True)
    cfg = tmp_path / "config"
    cfg.mkdir()

    app = FastAPI()
    MODULE.setup(
        app,
        {
            "log": type("L", (), {"info": lambda *a, **k: None, "warning": lambda *a, **k: None})(),
            "config_dir": cfg,
            "get_dlc_dir": lambda: dlc,
            "extract_meta": lambda path: {},
        },
    )
    client = TestClient(app)

    loaded = client.get("/api/plugins/feedpak_naming/settings")
    assert loaded.status_code == 200
    assert loaded.json()["include_builtin_content"] is False

    saved = client.post(
        "/api/plugins/feedpak_naming/settings",
        json={"include_builtin_content": True},
    )
    assert saved.status_code == 200
    assert saved.json()["include_builtin_content"] is True

    loaded_after = client.get("/api/plugins/feedpak_naming/settings")
    assert loaded_after.status_code == 200
    assert loaded_after.json()["include_builtin_content"] is True



def test_preview_excludes_builtin_folders_by_default(tmp_path):
    dlc = tmp_path / "dlc"
    (dlc / "sloppak").mkdir(parents=True)
    (dlc / "sloppak" / "inside.feedpak").write_text("fake")
    (dlc / "starter").mkdir(parents=True)
    (dlc / "starter" / "outside.feedpak").write_text("fake")
    (dlc / "diagnostics-builtin").mkdir(parents=True)
    (dlc / "diagnostics-builtin" / "diagnostic.sloppak").write_text("fake")
    (dlc / "tutorials-builtin" / "intro-bends").mkdir(parents=True)
    (dlc / "tutorials-builtin" / "intro-bends" / "lesson.sloppak").write_text("fake")
    (dlc / "legacy").mkdir(parents=True)
    (dlc / "legacy" / "old.sloppak").write_text("fake")
    cfg = tmp_path / "config"
    cfg.mkdir()

    app = FastAPI()
    MODULE.setup(
        app,
        {
            "log": type("L", (), {"info": lambda *a, **k: None, "warning": lambda *a, **k: None})(),
            "config_dir": cfg,
            "get_dlc_dir": lambda: dlc,
            "extract_meta": lambda path: {"artist": "A", "title": path.stem},
        },
    )
    client = TestClient(app)

    preview = client.get("/api/plugins/feedpak_naming/preview", params={"template": "{artist}_{title}.feedpak"})
    assert preview.status_code == 200
    rows = preview.json()["items"]
    current_paths = {row["current_relative_path"] for row in rows}
    assert "sloppak/inside.feedpak" in current_paths
    assert "legacy/old.sloppak" in current_paths
    assert "starter/outside.feedpak" not in current_paths
    assert "diagnostics-builtin/diagnostic.sloppak" not in current_paths
    assert "tutorials-builtin/intro-bends/lesson.sloppak" not in current_paths
    assert len(rows) == 2



def test_preview_can_include_builtin_folders_when_enabled(tmp_path):
    dlc = tmp_path / "dlc"
    (dlc / "sloppak").mkdir(parents=True)
    (dlc / "sloppak" / "inside.feedpak").write_text("fake")
    (dlc / "starter").mkdir(parents=True)
    (dlc / "starter" / "outside.feedpak").write_text("fake")
    (dlc / "diagnostics-builtin").mkdir(parents=True)
    (dlc / "diagnostics-builtin" / "diagnostic.sloppak").write_text("fake")
    (dlc / "tutorials-builtin" / "intro-bends").mkdir(parents=True)
    (dlc / "tutorials-builtin" / "intro-bends" / "lesson.sloppak").write_text("fake")
    (dlc / "legacy").mkdir(parents=True)
    (dlc / "legacy" / "old.sloppak").write_text("fake")
    cfg = tmp_path / "config"
    cfg.mkdir()

    app = FastAPI()
    MODULE.setup(
        app,
        {
            "log": type("L", (), {"info": lambda *a, **k: None, "warning": lambda *a, **k: None})(),
            "config_dir": cfg,
            "get_dlc_dir": lambda: dlc,
            "extract_meta": lambda path: {"artist": "A", "title": path.stem},
        },
    )
    client = TestClient(app)

    saved = client.post(
        "/api/plugins/feedpak_naming/settings",
        json={"include_builtin_content": True},
    )
    assert saved.status_code == 200

    preview = client.get("/api/plugins/feedpak_naming/preview", params={"template": "{artist}_{title}.feedpak"})
    assert preview.status_code == 200
    rows = preview.json()["items"]
    current_paths = {row["current_relative_path"] for row in rows}
    assert "sloppak/inside.feedpak" in current_paths
    assert "legacy/old.sloppak" in current_paths
    assert "starter/outside.feedpak" in current_paths
    assert "diagnostics-builtin/diagnostic.sloppak" in current_paths
    assert "tutorials-builtin/intro-bends/lesson.sloppak" in current_paths
    assert len(rows) == 5



def test_preview_scans_whole_dlc_root_and_legacy_sloppak_suffix(tmp_path):
    dlc = tmp_path / "dlc"
    (dlc / "sloppak").mkdir(parents=True)
    (dlc / "sloppak" / "inside.feedpak").write_text("fake")
    (dlc / "starter").mkdir(parents=True)
    (dlc / "starter" / "outside.feedpak").write_text("fake")
    (dlc / "legacy").mkdir(parents=True)
    (dlc / "legacy" / "old.sloppak").write_text("fake")
    cfg = tmp_path / "config"
    cfg.mkdir()

    app = FastAPI()
    MODULE.setup(
        app,
        {
            "log": type("L", (), {"info": lambda *a, **k: None, "warning": lambda *a, **k: None})(),
            "config_dir": cfg,
            "get_dlc_dir": lambda: dlc,
            "extract_meta": lambda path: {"artist": "A", "title": path.stem},
        },
    )
    client = TestClient(app)

    saved = client.post(
        "/api/plugins/feedpak_naming/settings",
        json={"include_builtin_content": True},
    )
    assert saved.status_code == 200

    preview = client.get("/api/plugins/feedpak_naming/preview", params={"template": "{artist}_{title}.feedpak"})
    assert preview.status_code == 200
    rows = preview.json()["items"]
    current_paths = {row["current_relative_path"] for row in rows}
    assert "sloppak/inside.feedpak" in current_paths
    assert "starter/outside.feedpak" in current_paths
    assert "legacy/old.sloppak" in current_paths
    assert len(rows) == 3


def test_apply_returns_json_error_when_rename_fails(tmp_path, monkeypatch):
    dlc = tmp_path / "dlc"
    lib = dlc / "sloppak"
    lib.mkdir(parents=True)
    source = lib / "Paramore_Hallelujah_v1_DD_p.feedpak"
    source.write_text("fake")
    cfg = tmp_path / "config"
    cfg.mkdir()

    def fake_extract_meta(path: Path):
        return {"artist": "Paramore", "title": "Hallelujah"}

    def boom(self, target):
        raise PermissionError("mock rename denied")

    monkeypatch.setattr(Path, "rename", boom)

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

    apply = client.post(
        "/api/plugins/feedpak_naming/apply",
        json={
            "template": "{artist}/{title}.feedpak",
            "selected_current_paths": ["sloppak/Paramore_Hallelujah_v1_DD_p.feedpak"],
        },
    )
    assert apply.status_code == 500
    body = apply.json()
    assert "Rename failed for sloppak/Paramore_Hallelujah_v1_DD_p.feedpak" in body["error"]
    assert body["failed"] == {
        "from": "sloppak/Paramore_Hallelujah_v1_DD_p.feedpak",
        "to": "Paramore/Hallelujah.feedpak",
    }
    assert body["renamed_count"] == 0
