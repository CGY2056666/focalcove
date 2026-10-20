"""Create and verify portable backups of the production JSON runtime.

The archive deliberately contains only the four persisted runtime roots used by
the Android MVP. Environment files, logs, screenshots, and source files are not
eligible for inclusion.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import tarfile
from datetime import datetime, timezone


RUNTIME_ROOTS = ("users.json", "mobile_sessions.json", "user_data", "user_history")
MANIFEST_NAME = "manifest.json"


def _sha256_stream(stream) -> str:
    digest = hashlib.sha256()
    while chunk := stream.read(1024 * 1024):
        digest.update(chunk)
    return digest.hexdigest()


def _runtime_files(runtime_dir: Path) -> list[Path]:
    files: list[Path] = []
    for name in RUNTIME_ROOTS:
        root = runtime_dir / name
        if not root.exists():
            continue
        if root.is_symlink():
            raise ValueError(f"Runtime backup refuses symbolic links: {root}")
        if root.is_file():
            files.append(root)
            continue
        if not root.is_dir():
            raise ValueError(f"Unsupported runtime entry: {root}")
        for candidate in sorted(root.rglob("*")):
            if candidate.is_symlink():
                raise ValueError(f"Runtime backup refuses symbolic links: {candidate}")
            if candidate.is_file():
                files.append(candidate)
    return sorted(files, key=lambda path: path.relative_to(runtime_dir).as_posix())


def create_backup(
    runtime_dir: str | Path,
    output_dir: str | Path,
    *,
    name: str | None = None,
) -> Path:
    runtime = Path(runtime_dir).expanduser().resolve()
    if not runtime.is_dir():
        raise ValueError(f"Runtime directory does not exist: {runtime}")
    if runtime == Path(runtime.anchor):
        raise ValueError("Runtime directory cannot be a filesystem root")

    files = _runtime_files(runtime)
    if not files:
        raise ValueError("Runtime directory contains no recognized persisted data")

    output = Path(output_dir).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    safe_name = name or f"focus-runtime-{timestamp}"
    if not safe_name.replace("-", "").replace("_", "").isalnum():
        raise ValueError("Backup name may contain only letters, numbers, '-' and '_'")
    destination = output / f"{safe_name}.tar.gz"
    temporary = output / f".{safe_name}.{os.getpid()}.tmp"
    if destination.exists():
        raise FileExistsError(f"Backup already exists: {destination}")

    manifest_files = []
    for path in files:
        relative = path.relative_to(runtime).as_posix()
        with path.open("rb") as stream:
            checksum = _sha256_stream(stream)
        manifest_files.append(
            {"path": relative, "size": path.stat().st_size, "sha256": checksum}
        )
    manifest = {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "runtime_roots": list(RUNTIME_ROOTS),
        "files": manifest_files,
    }
    manifest_bytes = json.dumps(
        manifest, ensure_ascii=False, indent=2, sort_keys=True
    ).encode("utf-8")

    try:
        with tarfile.open(temporary, "w:gz") as archive:
            for path in files:
                relative = path.relative_to(runtime).as_posix()
                info = archive.gettarinfo(str(path), arcname=relative)
                info.uid = 0
                info.gid = 0
                info.uname = ""
                info.gname = ""
                info.mode = 0o600
                with path.open("rb") as stream:
                    archive.addfile(info, stream)
            info = tarfile.TarInfo(MANIFEST_NAME)
            info.size = len(manifest_bytes)
            info.mode = 0o600
            info.mtime = int(datetime.now(timezone.utc).timestamp())
            archive.addfile(info, io.BytesIO(manifest_bytes))
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    return destination


def _safe_member_name(name: str) -> bool:
    path = PurePosixPath(name)
    return bool(name) and not path.is_absolute() and ".." not in path.parts


def verify_backup(archive_path: str | Path) -> dict:
    archive_file = Path(archive_path).expanduser().resolve()
    if not archive_file.is_file():
        raise ValueError(f"Backup archive does not exist: {archive_file}")
    with tarfile.open(archive_file, "r:gz") as archive:
        members = archive.getmembers()
        if any(not _safe_member_name(member.name) for member in members):
            raise ValueError("Backup contains an unsafe archive path")
        manifest_member = archive.getmember(MANIFEST_NAME)
        manifest_stream = archive.extractfile(manifest_member)
        if manifest_stream is None:
            raise ValueError("Backup manifest cannot be read")
        manifest = json.load(manifest_stream)
        if manifest.get("schema_version") != 1:
            raise ValueError("Unsupported backup manifest version")

        expected = {
            str(item["path"]): item for item in manifest.get("files", [])
        }
        actual_file_names = {
            member.name for member in members if member.isfile() and member.name != MANIFEST_NAME
        }
        if actual_file_names != set(expected):
            raise ValueError("Backup file list does not match its manifest")
        for name, item in expected.items():
            member = archive.getmember(name)
            stream = archive.extractfile(member)
            if stream is None:
                raise ValueError(f"Backup member cannot be read: {name}")
            checksum = _sha256_stream(stream)
            if member.size != int(item["size"]) or checksum != item["sha256"]:
                raise ValueError(f"Backup checksum mismatch: {name}")
    return manifest


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Back up Focus Compass runtime JSON data")
    commands = parser.add_subparsers(dest="command", required=True)
    backup = commands.add_parser("backup", help="create a verified tar.gz archive")
    backup.add_argument("--runtime-dir", required=True)
    backup.add_argument("--output-dir", required=True)
    backup.add_argument("--name")
    verify = commands.add_parser("verify", help="verify archive paths and SHA-256 checksums")
    verify.add_argument("archive")
    return parser


def main() -> int:
    args = _parser().parse_args()
    if args.command == "backup":
        archive = create_backup(args.runtime_dir, args.output_dir, name=args.name)
        manifest = verify_backup(archive)
        print(
            json.dumps(
                {
                    "status": "ok",
                    "archive": str(archive),
                    "file_count": len(manifest["files"]),
                },
                ensure_ascii=False,
            )
        )
        return 0
    manifest = verify_backup(args.archive)
    print(
        json.dumps(
            {"status": "ok", "file_count": len(manifest["files"])},
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
