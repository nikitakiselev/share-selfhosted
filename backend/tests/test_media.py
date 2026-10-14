from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import anyio
import pytest
from starlette.testclient import TestClient

from share_app.media import (
    MediaInfo,
    classify,
    guess_mime,
    kind_of,
    poster_time,
    remux_args,
)
from tests.conftest import new_share, upload

FFMPEG = shutil.which("ffmpeg")
FFPROBE = shutil.which("ffprobe")
needs_ffmpeg = pytest.mark.skipif(not (FFMPEG and FFPROBE), reason="no ffmpeg/ffprobe")

SRC = ["-f", "lavfi", "-i", "testsrc=duration=2:size=320x240:rate=25",
       "-f", "lavfi", "-i", "sine=frequency=440:duration=2"]


def _make(path: Path, *codec_args: str) -> Path:
    subprocess.run([FFMPEG, "-v", "error", "-y", *SRC, *codec_args, "-shortest", str(path)], check=True)
    return path


@pytest.fixture(scope="session")
def clips(tmp_path_factory) -> dict[str, Path]:
    if not (FFMPEG and FFPROBE):
        pytest.skip("no ffmpeg/ffprobe")
    d = tmp_path_factory.mktemp("clips")
    return {
        "mp4": _make(d / "h264_aac.mp4", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac"),
        "mkv": _make(d / "h264_ac3.mkv", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "ac3"),
        "avi": _make(d / "mpeg4.avi", "-c:v", "mpeg4", "-c:a", "pcm_s16le"),
        "webm": _make(d / "vp9_opus.webm", "-c:v", "libvpx-vp9", "-b:v", "200k", "-c:a", "libopus"),
        "png": _png(d / "still.png"),
    }


def _png(path: Path) -> Path:
    subprocess.run([FFMPEG, "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=1920x1080", "-frames:v", "1",
                    str(path)], check=True)
    return path


def _probe(path: Path) -> dict:
    out = subprocess.run([FFPROBE, "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)],
                         check=True, capture_output=True).stdout
    return json.loads(out)


# --- classification on "paper" ffprobe outputs ---

def _fake(fmt: str, *streams: dict, duration: str = "10.0") -> dict:
    return {"format": {"format_name": fmt, "duration": duration}, "streams": list(streams)}


V264 = {"codec_type": "video", "codec_name": "h264", "width": 1920, "height": 1080, "pix_fmt": "yuv420p"}
AAC = {"codec_type": "audio", "codec_name": "aac"}


def test_hevc_mov_is_maybe_original():
    hevc = {**V264, "codec_name": "hevc"}
    info = classify(_fake("mov,mp4,m4a,3gp,3g2,mj2", hevc, AAC), "IMG_0001.MOV", "video/quicktime")
    assert (info.kind, info.play, info.playable) == ("video", "original", "maybe")


def test_10bit_h264_is_maybe():
    info = classify(_fake("matroska,webm", {**V264, "pix_fmt": "yuv420p10le"}, AAC), "anime.mkv", "video/x-matroska")
    assert info.playable == "maybe" and info.play == "remux"


def test_mp4_with_unfriendly_audio_remuxed():
    info = classify(_fake("mov,mp4,m4a,3gp,3g2,mj2", V264, {"codec_type": "audio", "codec_name": "eac3"}),
                    "a.mp4", "video/mp4")
    assert info.play == "remux" and info.audio_copy is False


def test_vorbis_in_mkv_transcoded_for_mp4():
    info = classify(_fake("matroska,webm", V264, {"codec_type": "audio", "codec_name": "vorbis"}), "a.mkv", "")
    assert info.play == "remux" and info.audio_copy is False


def test_rotation_swaps_dimensions():
    rotated = {**V264, "side_data_list": [{"side_data_type": "Display Matrix", "rotation": -90}]}
    info = classify(_fake("mov,mp4,m4a,3gp,3g2,mj2", rotated, AAC), "a.mov", "video/quicktime")
    assert (info.width, info.height) == (1080, 1920)


def test_audio_only_and_cover_art():
    cover = {"codec_type": "video", "codec_name": "mjpeg", "disposition": {"attached_pic": 1}}
    mp3 = {"codec_type": "audio", "codec_name": "mp3"}
    info = classify(_fake("mp3", cover, mp3), "song.mp3", "audio/mpeg")
    assert (info.kind, info.play, info.playable) == ("audio", "original", "yes")
    wma = classify(_fake("asf", {"codec_type": "audio", "codec_name": "wmav2"}), "a.wma", "audio/x-ms-wma")
    assert (wma.kind, wma.play) == ("audio", "none")


def test_mime_guessing():
    assert guess_mime("a.mkv", "") == "video/x-matroska"
    assert guess_mime("a.mkv", "application/octet-stream") == "video/x-matroska"
    assert guess_mime("a.mov", "video/quicktime") == "video/quicktime"
    assert guess_mime("a.bin", "text/html; charset=utf-8") == "text/html"
    assert guess_mime("a.weird", "not a mime") == "application/octet-stream"
    assert kind_of("image/heic") == "image" and kind_of("application/pdf") == "other"


def test_poster_time_and_remux_args(tmp_path):
    assert poster_time(None) == 0 and poster_time(10) == 1.0 and poster_time(7200) == 30.0
    info = MediaInfo(kind="video", play="remux", video_codec="hevc", audio_copy=False)
    args = remux_args("ffmpeg", tmp_path / "in.mkv", tmp_path / "out.mp4", info)
    assert ["-tag:v", "hvc1"] == args[args.index("-tag:v"):args.index("-tag:v") + 2]
    assert args[args.index("-c:a") + 1] == "aac" and "+faststart" in args


# --- real clips ---

@needs_ffmpeg
def test_classify_real_clips(clips):
    mp4 = classify(_probe(clips["mp4"]), "a.mp4", "video/mp4")
    assert (mp4.kind, mp4.play, mp4.playable, mp4.video_codec, mp4.audio_codec) == (
        "video", "original", "yes", "h264", "aac")
    assert (mp4.width, mp4.height) == (320, 240) and 1.5 < mp4.duration < 2.5

    mkv = classify(_probe(clips["mkv"]), "a.mkv", "video/x-matroska")
    assert (mkv.play, mkv.playable, mkv.audio_codec, mkv.audio_copy) == ("remux", "yes", "ac3", False)

    avi = classify(_probe(clips["avi"]), "a.avi", "video/x-msvideo")
    assert (avi.kind, avi.play, avi.playable) == ("video", "none", "no")

    webm = classify(_probe(clips["webm"]), "a.webm", "video/webm")
    assert (webm.play, webm.playable) == ("original", "yes")

    png = classify(_probe(clips["png"]), "a.png", "image/png")
    assert (png.kind, png.play) == ("image", "none") and png.width == 1920


def _upload_clip(admin: TestClient, path: Path, mime: str) -> tuple[str, str]:
    slug = new_share(admin)["slug"]
    fid = upload(admin, slug, path.read_bytes(), path.name, mime)
    return slug, fid


@needs_ffmpeg
def test_worker_remuxes_mkv_with_aac(admin: TestClient, outsider: TestClient, ctx, clips):
    slug, fid = _upload_clip(admin, clips["mkv"], "video/x-matroska")
    f = outsider.get(f"/api/public/shares/{slug}").json()["files"][0]
    assert f["media_status"] == "pending" and f["play_url"] is None and f["url"]  # downloading already works

    assert anyio.run(ctx.worker.run_pending) == 1
    f = outsider.get(f"/api/public/shares/{slug}").json()["files"][0]
    assert f["media_status"] == "done" and f["playable"] == "yes"
    assert f["play_url"] == f"/api/public/shares/{slug}/files/{fid}/play"
    assert f["poster_url"] == f"/api/public/shares/{slug}/files/{fid}/poster.jpg"

    play = ctx.storage.play_path(fid)
    probe = _probe(play)
    assert "mp4" in probe["format"]["format_name"]
    codecs = {s["codec_type"]: s["codec_name"] for s in probe["streams"]}
    assert codecs == {"video": "h264", "audio": "aac"}
    assert not list(ctx.storage.derived_dir(fid).glob("*.tmp*"))

    r = outsider.get(f["play_url"], headers={"Range": "bytes=0-99"})
    assert r.status_code == 206 and r.headers["content-type"] == "video/mp4"
    assert r.headers["content-disposition"].startswith("inline") and 'h264_ac3.mp4' in r.headers["content-disposition"]
    p = outsider.get(f["poster_url"])
    assert p.status_code == 200 and p.content[:2] == b"\xff\xd8"  # JPEG
    # both the remux and the poster go away with the file
    admin.delete(f"/api/app/shares/{slug}/files/{fid}")
    assert not ctx.storage.derived_dir(fid).exists()


@needs_ffmpeg
def test_worker_mp4_plays_original(admin: TestClient, outsider: TestClient, ctx, clips):
    slug, fid = _upload_clip(admin, clips["mp4"], "video/mp4")
    anyio.run(ctx.worker.run_pending)
    f = ctx.db.get_file(fid)
    assert (f["play"], f["has_poster"]) == ("original", 1)
    assert not ctx.storage.play_path(fid).exists()
    r = outsider.get(f"/api/public/shares/{slug}/files/{fid}/play")
    assert r.content == clips["mp4"].read_bytes()


@needs_ffmpeg
def test_worker_unplayable_avi(admin: TestClient, outsider: TestClient, ctx, clips):
    slug, fid = _upload_clip(admin, clips["avi"], "video/x-msvideo")
    anyio.run(ctx.worker.run_pending)
    f = outsider.get(f"/api/public/shares/{slug}").json()["files"][0]
    assert f["media_status"] == "done" and f["playable"] == "no" and f["play_url"] is None
    assert f["poster_url"]  # the poster is there anyway: ffmpeg decodes MPEG-4 ASP
    assert outsider.get(f"/api/public/shares/{slug}/files/{fid}/play").status_code == 404


@needs_ffmpeg
def test_worker_image_poster(admin: TestClient, ctx, clips):
    _, fid = _upload_clip(admin, clips["png"], "image/png")
    anyio.run(ctx.worker.run_pending)
    f = ctx.db.get_file(fid)
    assert f["kind"] == "image" and f["has_poster"] == 1 and f["width"] == 1920
    probe = _probe(ctx.storage.poster_path(fid))
    assert probe["streams"][0]["width"] == 1280


def test_worker_marks_garbage_failed(admin: TestClient, ctx):
    slug = new_share(admin)["slug"]
    fid = upload(admin, slug, b"definitely not a video", "broken.mp4", "video/mp4")
    anyio.run(ctx.worker.run_pending)
    f = ctx.db.get_file(fid)
    assert f["media_status"] == "failed" and f["status"] == "ready"


def test_non_media_not_queued(admin: TestClient, ctx):
    slug = new_share(admin)["slug"]
    fid = upload(admin, slug, b"%PDF-1.4", "doc.pdf", "application/pdf")
    assert ctx.db.get_file(fid)["media_status"] == "none"
    assert anyio.run(ctx.worker.run_pending) == 0
