"""Streaming ZIP without compression: the size is known up front, no temp files.

Video and archives do not compress anyway, and ZIP_STORED lets us compute the final size
before sending — the recipient gets a proper download progress. zipstream-ng enables ZIP64
for files over 4 GB by itself.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterable
from pathlib import Path, PurePosixPath

import anyio
from zipstream import ZipStream

BATCH = 1 << 20


def unique_names(names: Iterable[str]) -> list[str]:
    """Duplicate names inside the archive → `name (2).ext`, `name (3).ext`."""
    seen: set[str] = set()
    out: list[str] = []
    for name in names:
        candidate = name
        if candidate.lower() in seen:
            p = PurePosixPath(name)
            stem, suffix = (p.stem, p.suffix) if p.stem else (name, "")
            n = 2
            while (candidate := f"{stem} ({n}){suffix}").lower() in seen:
                n += 1
        seen.add(candidate.lower())
        out.append(candidate)
    return out


def build_zip(entries: Iterable[tuple[Path, str]]) -> ZipStream:
    zs = ZipStream(sized=True)
    for path, arcname in entries:
        zs.add_path(str(path), arcname)
    return zs


async def stream_zip(zs: ZipStream) -> AsyncIterator[bytes]:
    """zipstream iteration is synchronous (it reads files) — run it in a thread in 1 MiB batches."""
    it = iter(zs)

    def batch() -> tuple[bytes, bool]:
        buf = bytearray()
        for chunk in it:
            buf += chunk
            if len(buf) >= BATCH:
                return bytes(buf), False
        return bytes(buf), True

    while True:
        data, done = await anyio.to_thread.run_sync(batch)
        if data:
            yield data
        if done:
            break
