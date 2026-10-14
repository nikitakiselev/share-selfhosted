"""On-disk data layout.

Paths are built only from a file_id issued by the server itself — a user-supplied file
name never ends up in a path.
"""

from __future__ import annotations

import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

FILE_ID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")


@dataclass(frozen=True)
class Disk:
    total: int
    used: int
    free: int


class Storage:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.uploads = root / "uploads"
        self.files = root / "files"
        self.derived = root / "derived"
        self.db_path = root / "share.db"

    def ensure_dirs(self) -> None:
        for d in (self.uploads, self.files, self.derived):
            d.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _check(file_id: str) -> str:
        if not FILE_ID_RE.match(file_id):
            raise ValueError(f"invalid file_id {file_id!r}")
        return file_id

    def upload_path(self, file_id: str) -> Path:
        return self.uploads / self._check(file_id)

    def file_path(self, file_id: str) -> Path:
        return self.files / self._check(file_id)

    def derived_dir(self, file_id: str) -> Path:
        return self.derived / self._check(file_id)

    def play_path(self, file_id: str) -> Path:
        return self.derived_dir(file_id) / "play.mp4"

    def poster_path(self, file_id: str) -> Path:
        return self.derived_dir(file_id) / "poster.jpg"

    def upload_offset(self, file_id: str) -> int | None:
        try:
            return self.upload_path(file_id).stat().st_size
        except FileNotFoundError:
            return None

    def remove(self, file_id: str) -> None:
        """Everything on disk for a file: partial upload, original, remux, poster."""
        for p in (self.upload_path(file_id), self.file_path(file_id)):
            try:
                p.unlink()
            except FileNotFoundError:
                pass
        shutil.rmtree(self.derived_dir(file_id), ignore_errors=True)

    def ids_on_disk(self) -> set[str]:
        ids: set[str] = set()
        for d in (self.uploads, self.files, self.derived):
            if d.is_dir():
                ids.update(p.name for p in d.iterdir() if FILE_ID_RE.match(p.name))
        return ids

    def stray_entries(self) -> list[Path]:
        """Everything that does not look like a file_id: temp files and leftovers of interrupted operations."""
        out: list[Path] = []
        for d in (self.uploads, self.files, self.derived):
            if d.is_dir():
                out.extend(p for p in d.iterdir() if not FILE_ID_RE.match(p.name))
        return out

    def disk(self) -> Disk:
        st = os.statvfs(self.root)
        total = st.f_blocks * st.f_frsize
        return Disk(total=total, used=total - st.f_bfree * st.f_frsize, free=st.f_bavail * st.f_frsize)
