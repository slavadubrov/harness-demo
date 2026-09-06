"""Capture submitted bytes, independently of Git's index or model narration."""

from __future__ import annotations

import hashlib
import json
import stat
from dataclasses import dataclass
from pathlib import Path

MAX_BYTES = 64 * 1024
MAX_FILES = 32


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@dataclass(frozen=True)
class File:
    path: str
    content: bytes
    mode: int = 0o644


@dataclass(frozen=True)
class Artifact:
    files: tuple[File, ...]

    def __post_init__(self) -> None:
        names = [file.path for file in self.files]
        if not names or len(names) > MAX_FILES or len(set(names)) != len(names):
            raise ValueError("Artifact must have 1–32 uniquely named files")
        if sum(len(file.content) for file in self.files) > MAX_BYTES:
            raise ValueError("Artifact exceeds 64 KiB")
        for file in self.files:
            path = Path(file.path)
            if (
                path.is_absolute()
                or path.as_posix() != file.path
                or any(part in {"..", ".git"} for part in path.parts)
                or not path.parts
            ):
                raise ValueError("Artifact paths must be normalized relative paths")
            if any(part.startswith(".env") for part in path.parts):
                raise ValueError("Do not submit environment files as evaluation data")

    def manifest(self) -> list[dict[str, str | int]]:
        return [
            {"path": file.path, "hex": file.content.hex(), "mode": file.mode}
            for file in sorted(self.files, key=lambda file: file.path)
        ]

    @property
    def sha256(self) -> str:
        return digest(json.dumps(self.manifest(), sort_keys=True).encode())


def capture(root: Path) -> Artifact:
    """Include dirty, ignored and untracked bytes; never follow symlinks.

    The resulting value describes the captured bytes, not an atomic filesystem
    transaction. Acceptance recaptures the source; execution uses only the value.
    """
    if root.is_symlink() or not root.is_dir():
        raise ValueError("Submission must be a regular directory")
    files: list[File] = []
    total = 0
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if relative.parts[0] == ".git":
            continue
        mode = path.lstat().st_mode
        if stat.S_ISDIR(mode):
            continue
        if not stat.S_ISREG(mode):
            raise ValueError("Submission contains a symlink or special file")
        with path.open("rb") as stream:
            content = stream.read(MAX_BYTES + 1)
        total += len(content)
        if total > MAX_BYTES or len(files) >= MAX_FILES:
            raise ValueError("Submission exceeds the file or byte limit")
        files.append(File(relative.as_posix(), content, stat.S_IMODE(mode)))
    return Artifact(tuple(files))


def candidate(text: str) -> Artifact:
    return Artifact((File("config.json", text.encode()),))


def json_bytes(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=True).encode()


def write_json(path: Path, value: object) -> None:
    """Atomically replace a local report; no partial success-looking JSON."""
    import os
    import tempfile

    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        try:
            stream.write(json_bytes(value) + b"\n")
            stream.flush()
            os.fsync(stream.fileno())
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
    try:
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
