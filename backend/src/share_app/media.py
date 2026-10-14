"""Media: ffprobe classification, remux to MP4 without re-encoding video, poster.

One worker processes files one at a time (ffmpeg under `nice -n 10`). The queue is
the DB itself (`media_status = 'pending'`), so unfinished work is picked up after a
restart without separate state.
"""

from __future__ import annotations

import asyncio
import json
import logging
import mimetypes
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from share_app import clock
from share_app.config import Settings
from share_app.db import Database
from share_app.storage import Storage

log = logging.getLogger("share.media")

VIDEO_YES = {"h264", "vp8", "vp9", "av1"}
VIDEO_MAYBE = {"hevc"}
AUDIO_OK = {"aac", "mp3", "opus", "vorbis", "flac"}
# what the MP4 muxer accepts as is; anything else is re-encoded to AAC during remux
AUDIO_MP4_COPY = {"aac", "mp3", "opus", "flac"}
# "video stream" codecs of images and cover art
STILL_CODECS = {"mjpeg", "png", "bmp", "tiff", "webp", "gif"}
MEDIA_KINDS = {"video", "audio", "image"}

EXTRA_TYPES = {
    ".mkv": "video/x-matroska", ".webm": "video/webm", ".mov": "video/quicktime",
    ".m4v": "video/x-m4v", ".mp4": "video/mp4", ".ts": "video/mp2t", ".m2ts": "video/mp2t",
    ".mts": "video/mp2t", ".avi": "video/x-msvideo", ".heic": "image/heic", ".heif": "image/heif",
    ".webp": "image/webp", ".avif": "image/avif", ".flac": "audio/flac", ".opus": "audio/ogg",
    ".m4a": "audio/mp4", ".mp3": "audio/mpeg", ".wav": "audio/wav", ".ogg": "audio/ogg",
}
MIME_RE = re.compile(r"^[a-z0-9][a-z0-9.+-]*/[a-z0-9][a-z0-9.+-]*$")


def guess_mime(name: str, declared: str | None) -> str:
    """The browser's type if it is meaningful, otherwise by extension."""
    mime = (declared or "").split(";")[0].strip().lower()
    if mime and mime != "application/octet-stream" and MIME_RE.match(mime):
        return mime
    ext = Path(name).suffix.lower()
    return EXTRA_TYPES.get(ext) or mimetypes.guess_type(name)[0] or "application/octet-stream"


def kind_of(mime: str) -> str:
    for kind in ("video", "audio", "image"):
        if mime.startswith(kind + "/"):
            return kind
    return "other"


@dataclass
class MediaInfo:
    kind: str
    play: str = "none"          # none | original | remux
    playable: str = "no"        # yes | maybe | no
    duration: float | None = None
    width: int | None = None
    height: int | None = None
    video_codec: str | None = None
    audio_codec: str | None = None
    audio_copy: bool = True     # audio is copied during remux (otherwise — to AAC)


def _rotation(stream: dict[str, Any]) -> int:
    for sd in stream.get("side_data_list") or []:
        if "rotation" in sd:
            try:
                return int(float(sd["rotation"]))
            except (TypeError, ValueError):
                return 0
    try:
        return int((stream.get("tags") or {}).get("rotate", 0))
    except (TypeError, ValueError):
        return 0


def classify(probe: dict[str, Any], name: str, mime: str) -> MediaInfo:
    """What the file is and how to play it in a browser. A pure function — tested on ffprobe output."""
    streams = probe.get("streams") or []
    fmt = probe.get("format") or {}
    videos = [s for s in streams if s.get("codec_type") == "video"
              and not (s.get("disposition") or {}).get("attached_pic")]
    audios = [s for s in streams if s.get("codec_type") == "audio"]
    try:
        duration = float(fmt["duration"]) if fmt.get("duration") not in (None, "N/A") else None
    except (TypeError, ValueError):
        duration = None

    vcodec = videos[0].get("codec_name") if videos else None
    acodec = audios[0].get("codec_name") if audios else None

    if mime.startswith("image/"):
        kind = "image"
    elif videos and (mime.startswith("video/") or vcodec not in STILL_CODECS):
        kind = "video"
    elif audios:
        kind = "audio"
    elif videos:
        kind = "image"
    else:
        kind = "other"

    info = MediaInfo(kind=kind, duration=duration, video_codec=vcodec, audio_codec=acodec)

    if videos:
        v = videos[0]
        w, h = v.get("width"), v.get("height")
        if w and h and abs(_rotation(v)) % 180 == 90:
            w, h = h, w
        info.width, info.height = w, h

    if kind == "video":
        pix_fmt = videos[0].get("pix_fmt") or ""
        if vcodec in VIDEO_YES:
            # 10-bit H.264 (High 10) is decoded by almost no browser
            info.playable = "maybe" if (vcodec == "h264" and "10" in pix_fmt) else "yes"
        elif vcodec in VIDEO_MAYBE:
            info.playable = "maybe"
        if info.playable == "no":
            return info
        formats = set((fmt.get("format_name") or "").split(","))
        container_ok = bool(formats & {"mp4", "mov"}) or (
            Path(name).suffix.lower() == ".webm" and "webm" in formats
        )
        audio_ok = acodec is None or acodec in AUDIO_OK
        info.play = "original" if container_ok and audio_ok else "remux"
        info.audio_copy = acodec is None or acodec in AUDIO_MP4_COPY
    elif kind == "audio":
        if acodec in AUDIO_OK or (acodec or "").startswith("pcm_"):
            info.play, info.playable = "original", "yes"
    return info


def poster_time(duration: float | None) -> float:
    if not duration or duration <= 0:
        return 0.0
    return min(duration * 0.1, 30.0)


def remux_args(ffmpeg: str, src: Path, dst: Path, info: MediaInfo) -> list[str]:
    args = [ffmpeg, "-nostdin", "-v", "error", "-y", "-i", str(src),
            "-map", "0:v:0", "-map", "0:a:0?", "-c:v", "copy"]
    if info.video_codec == "hevc":
        args += ["-tag:v", "hvc1"]  # without this Safari does not play HEVC in MP4
    if info.audio_copy:
        args += ["-c:a", "copy"]
    else:
        args += ["-c:a", "aac", "-b:a", "192k", "-ac", "2"]
    args += ["-movflags", "+faststart", "-f", "mp4", str(dst)]
    return args


def poster_args(ffmpeg: str, src: Path, dst: Path, at: float) -> list[str]:
    args = [ffmpeg, "-nostdin", "-v", "error", "-y"]
    if at > 0:
        args += ["-ss", f"{at:.3f}"]
    args += ["-i", str(src), "-frames:v", "1", "-vf", "scale='min(1280,iw)':-2",
             "-q:v", "3", "-update", "1", "-f", "image2", str(dst)]
    return args


class MediaError(Exception):
    pass


class MediaWorker:
    def __init__(self, settings: Settings, db: Database, storage: Storage) -> None:
        self.settings = settings
        self.db = db
        self.storage = storage
        self._wake = asyncio.Event()
        self._task: asyncio.Task | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._current: str | None = None
        self._proc: asyncio.subprocess.Process | None = None
        self._nice = ["nice", "-n", "10"] if shutil.which("nice") else []

    # --- control ---

    def start(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._wake = asyncio.Event()
        self._task = asyncio.create_task(self._run(), name="media-worker")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    def enqueue(self) -> None:
        """Wake the worker. Safe to call from any thread."""
        if self._loop is None:
            return
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is self._loop:
            self._wake.set()
        else:
            self._loop.call_soon_threadsafe(self._wake.set)

    def cancel(self, file_id: str) -> None:
        """The file was deleted — do not spend CPU remuxing it. Safe to call from any thread."""
        if self._loop is None:
            return
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is self._loop:
            self._kill_if(file_id)
        else:
            self._loop.call_soon_threadsafe(self._kill_if, file_id)

    def _kill_if(self, file_id: str) -> None:
        if self._current == file_id and self._proc and self._proc.returncode is None:
            self._proc.kill()

    async def _run(self) -> None:
        while True:
            # clear the flag first, then look at the DB: otherwise an enqueue() could be missed
            self._wake.clear()
            f = self.db.next_pending_media()
            if f is None:
                await self._wake.wait()
                continue
            await self.process(f)

    async def run_pending(self) -> int:
        """Process everything pending and return. For tests and manual runs."""
        n = 0
        while (f := self.db.next_pending_media()) is not None:
            await self.process(f)
            n += 1
        return n

    # --- processing ---

    async def _exec(self, args: list[str], timeout: float | None) -> tuple[int, bytes, bytes]:
        proc = await asyncio.create_subprocess_exec(
            *self._nice, *args,
            stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        self._proc = proc
        try:
            out, err = await asyncio.wait_for(proc.communicate(), timeout)
        except BaseException:
            if proc.returncode is None:
                proc.kill()
                await proc.wait()
            raise
        finally:
            self._proc = None
        return proc.returncode or 0, out, err

    async def probe(self, src: Path) -> dict[str, Any]:
        code, out, err = await self._exec(
            [self.settings.ffprobe, "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(src)],
            timeout=120,
        )
        if code != 0:
            raise MediaError(f"ffprobe: {err.decode(errors='replace').strip()[:500]}")
        return json.loads(out or b"{}")

    async def _poster(self, src: Path, dst: Path, at: float) -> bool:
        tmp = dst.with_name("poster.tmp.jpg")
        for t in ([at, 0.0] if at > 0 else [0.0]):
            code, _, err = await self._exec(poster_args(self.settings.ffmpeg, src, tmp, t), timeout=300)
            if code == 0 and tmp.exists() and tmp.stat().st_size > 0:
                tmp.replace(dst)
                return True
        tmp.unlink(missing_ok=True)
        log.warning("poster for %s failed: %s", src.name, err.decode(errors="replace").strip()[:300])
        return False

    async def _remux(self, src: Path, dst: Path, info: MediaInfo) -> None:
        tmp = dst.with_name("play.tmp.mp4")
        code, _, err = await self._exec(remux_args(self.settings.ffmpeg, src, tmp, info), timeout=None)
        if code != 0:
            tmp.unlink(missing_ok=True)
            raise MediaError(f"remux: {err.decode(errors='replace').strip()[:500]}")
        tmp.replace(dst)

    async def process(self, f: dict[str, Any]) -> None:
        fid = f["id"]
        src = self.storage.file_path(fid)
        ddir = self.storage.derived_dir(fid)
        self._current = fid
        started = clock.now()
        try:
            if not src.exists():
                raise MediaError("the original is gone from disk")
            info = classify(await self.probe(src), f["name"], f["mime"])
            ddir.mkdir(parents=True, exist_ok=True)
            has_poster = False
            if info.kind in ("video", "image"):
                has_poster = await self._poster(src, self.storage.poster_path(fid), poster_time(info.duration))
            if info.play == "remux":
                await self._remux(src, self.storage.play_path(fid), info)
            if self.db.get_file(fid) is None:  # deleted while being processed
                shutil.rmtree(ddir, ignore_errors=True)
                return
            self.db.update_file(
                fid, media_status="done", kind=info.kind, play=info.play, playable=info.playable,
                duration=info.duration, width=info.width, height=info.height,
                video_codec=info.video_codec, audio_codec=info.audio_codec, has_poster=int(has_poster),
            )
            log.info("processed %s/%s %r: %s, play=%s, %d s", f["share_slug"], fid, f["name"],
                     info.kind, info.play, clock.now() - started)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 — no ffmpeg failure may crash the worker
            if self.db.get_file(fid) is None:
                shutil.rmtree(ddir, ignore_errors=True)
                return
            log.error("processing %s/%s %r failed: %s", f["share_slug"], fid, f["name"], exc)
            self.db.update_file(fid, media_status="failed", play="none")
        finally:
            self._current = None
