from __future__ import annotations

import io
import json
import tarfile

import pytest

from scripts.runtime_backup import create_backup, verify_backup


def test_runtime_backup_round_trip(tmp_path) -> None:
    runtime = tmp_path / "runtime"
    (runtime / "user_data").mkdir(parents=True)
    (runtime / "user_history").mkdir()
    (runtime / "users.json").write_text('{"alice": {"password": "hash"}}', encoding="utf-8")
    (runtime / "mobile_sessions.json").write_text("{}", encoding="utf-8")
    (runtime / "user_data" / "alice_data.json").write_text(
        '{"total_points": 3}', encoding="utf-8"
    )
    (runtime / "user_history" / "alice_history.json").write_text(
        "[]", encoding="utf-8"
    )

    archive = create_backup(runtime, tmp_path / "backups", name="release_test")
    manifest = verify_backup(archive)

    assert archive.name == "release_test.tar.gz"
    assert [item["path"] for item in manifest["files"]] == [
        "mobile_sessions.json",
        "user_data/alice_data.json",
        "user_history/alice_history.json",
        "users.json",
    ]


def test_runtime_backup_rejects_empty_runtime(tmp_path) -> None:
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    with pytest.raises(ValueError, match="no recognized"):
        create_backup(runtime, tmp_path / "backups")


def test_runtime_backup_rejects_unsafe_archive_paths(tmp_path) -> None:
    archive = tmp_path / "unsafe.tar.gz"
    manifest = json.dumps({"schema_version": 1, "files": []}).encode()
    with tarfile.open(archive, "w:gz") as output:
        unsafe = tarfile.TarInfo("../escape.json")
        unsafe.size = 2
        output.addfile(unsafe, io.BytesIO(b"{}"))
        info = tarfile.TarInfo("manifest.json")
        info.size = len(manifest)
        output.addfile(info, io.BytesIO(manifest))
    with pytest.raises(ValueError, match="unsafe"):
        verify_backup(archive)
