#!/usr/bin/env python3
"""Подготовить и зарегистрировать локальные мультимедийные свидетельства."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import re
import shutil
import subprocess
import sys
from time import monotonic
from types import SimpleNamespace
import wave

import strategist

SCHEMA = "strategist.media/1.0"
IMAGES = {".png": b"\x89PNG\r\n\x1a\n", ".jpg": b"\xff\xd8\xff", ".jpeg": b"\xff\xd8\xff"}
VIDEO = {".mp4": "mov", ".mov": "mov", ".webm": "matroska", ".mkv": "matroska"}
AUDIO = {".wav": "wav", ".mp3": "mp3", ".m4a": "mov", ".ogg": "ogg", ".flac": "flac"}
MAX_SECONDS = 120
MAX_BYTES = 100 * 1024 * 1024


class MediaError(ValueError):
    pass


def outcome(status, reason=None, **data):
    if reason:
        data["reason"] = reason
    return {"status": status, **data}


def run(command, timeout=120):
    try:
        result = subprocess.run(command, capture_output=True, text=True, errors="replace", timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise MediaError(f"{command[0]} превысил лимит {timeout} с.") from exc
    except OSError as exc:
        raise MediaError(f"Не удалось запустить {command[0]}: {exc.strerror}.") from exc
    if result.returncode:
        raise MediaError(f"{command[0]} завершился с кодом {result.returncode}.")
    return result


def describe(root, path):
    return {"path": path.relative_to(root).as_posix(), "bytes": path.stat().st_size,
            "sha256": strategist.sha256(path)}


def verified_path(root, item):
    path = (root / item["path"]).resolve()
    if (not path.is_relative_to(root) or not path.is_file() or
            path.stat().st_size != item["bytes"] or strategist.sha256(path) != item["sha256"]):
        raise MediaError(f"Файл медиапакета отсутствует, вышел за его пределы или изменился: {item['path']}")
    return path


def load_bundle(value):
    root = Path(value).resolve()
    path = (root / "manifest.json").resolve()
    if not path.is_relative_to(root):
        raise MediaError("Опись находится вне медиапакета.")
    manifest = strategist.load_json(path, {})
    if not isinstance(manifest, dict) or manifest.get("schema") != SCHEMA:
        raise MediaError("Поддерживаемый manifest.json отсутствует.")
    return root, manifest


def check_image_signature(path):
    signature = IMAGES.get(path.suffix.lower())
    with path.open("rb") as file:
        if not signature or file.read(len(signature)) != signature:
            raise MediaError("Нужны PNG или JPEG с сигнатурой, соответствующей расширению.")


def media_input(suffix, path):
    # Разрешаем только локальный файл и явно выбираем демультиплексор. Плейлисты
    # и внешние MOV data references не входят в поддерживаемый ввод.
    demuxer = (VIDEO | AUDIO)[suffix]
    options = ["-protocol_whitelist", "file", "-f", demuxer]
    if demuxer == "mov":
        options += ["-enable_drefs", "0"]
    return [*options, "-i", str(path)]


def probe(media_args):
    result = run(["ffprobe", "-v", "error", "-show_entries",
                  "format=duration,start_time:stream=index,codec_type,start_time:stream_disposition=attached_pic",
                  "-of", "json", *media_args], timeout=30)
    payload = json.loads(result.stdout)
    try:
        seconds = float(payload["format"]["duration"])
    except (KeyError, TypeError, ValueError) as exc:
        raise MediaError("FFprobe не определил длительность.") from exc
    if not math.isfinite(seconds) or not 0 < seconds <= MAX_SECONDS:
        raise MediaError(f"Поддерживаются записи длительностью до {MAX_SECONDS} с.")
    return payload, seconds


def first_stream(payload, kind):
    return next((row for row in payload.get("streams", [])
                 if row["codec_type"] == kind and not row.get("disposition", {}).get("attached_pic")), None)


def sample_video(root, media_args, stream, duration, count):
    if stream is None:
        return outcome("no_stream", "В контейнере нет видеодорожки.")
    folder = root / "frames"
    folder.mkdir()
    select = rf"select=gte(t\,0)*(isnan(prev_selected_t)+gte(t-prev_selected_t\,{duration / count:.9f}))"
    filters = (select + r",scale=w=min(iw\,1280):h=min(ih\,1280):force_original_aspect_ratio=decrease,showinfo")
    result = run(["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "info", "-copyts", "-start_at_zero",
                  *media_args, "-map", f"0:{stream['index']}", "-an", "-vf", filters, "-fps_mode", "passthrough",
                  "-frames:v", str(count), "-c:v", "png", "-threads:v", "1", str(folder / "%03d.png")])
    seconds = [float(value) for value in re.findall(
        r"(?m)^\[Parsed_showinfo[^\n]+\bn:\s*\d+\s+pts:\s*\S+\s+pts_time:(\S+)", result.stderr)]
    images = sorted(folder.glob("*.png"))
    if not images or len(images) != len(seconds):
        raise MediaError("FFmpeg вернул неполный список кадров или меток PTS.")
    frames = [{"locator": f"frame:{timestamp:.3f}", "source_seconds": timestamp, **describe(root, path)}
              for path, timestamp in zip(images, seconds)]
    if len({frame["locator"] for frame in frames}) != len(frames):
        raise MediaError("У выборки кадров совпадают метки времени.")
    return outcome("ready", items=frames, stream_index=stream["index"], requested_count=count,
                   spacing_seconds=duration / count, clock="container_start")


def extract_audio(root, media_args, stream, duration):
    if stream is None:
        return outcome("no_stream", "В контейнере нет звуковой дорожки.")
    wav = root / "audio.wav"
    run(["ffmpeg", "-nostdin", "-hide_banner", "-v", "error", "-copyts", "-start_at_zero",
         *media_args, "-map", f"0:{stream['index']}", "-vn", "-t", str(duration),
         "-af", "aresample=16000:async=1000:first_pts=0", "-ac", "1", "-c:a", "pcm_s16le", str(wav)])
    return outcome("ready", stream_index=stream["index"], clock="container_start", file=describe(root, wav))


def transcribe(root, audio, model, language):
    if not model:
        return outcome("not_requested", "Для локальной расшифровки передайте --whisper-model.")
    if audio["status"] != "ready":
        return outcome("unavailable", "Для распознавания нужна извлечённая звуковая дорожка.")
    if not shutil.which("whisper-cli") or not model.is_file():
        return outcome("unavailable", "Нужны исполняемый whisper-cli и локальный файл модели.")
    output = root / "whisper"
    audio_path = root / audio["file"]["path"]
    start = monotonic()
    run(["whisper-cli", "--model", str(model.resolve()), "--file", str(audio_path),
         "--language", language, "--threads", "2", "--no-gpu", "--output-json", "--output-file", str(output)])
    raw = output.with_suffix(".json")
    try:
        with wave.open(str(audio_path), "rb") as wav:
            duration_ms = 1000 * wav.getnframes() // wav.getframerate()
        payload = strategist.load_json(raw, {})
        segments = []
        for row in payload["transcription"]:
            first, last = row["offsets"]["from"], row["offsets"]["to"]
            text = row["text"].strip()
            if not isinstance(first, int) or not isinstance(last, int) or not 0 <= first < min(last, duration_ms):
                raise ValueError("invalid interval")
            if text:
                end = min(last, duration_ms)
                segment = {"locator": f"audio:{first / 1000:.3f}-{end / 1000:.3f}",
                           "start_ms": first, "end_ms": end, "text": text}
                if end < last:
                    segment["model_end_ms"] = last
                segments.append(segment)
    except (AttributeError, KeyError, TypeError, ValueError, wave.Error) as exc:
        raise MediaError("whisper-cli не вернул ожидаемый JSON с интервалами.") from exc
    if isinstance(payload.get("params"), dict) and "model" in payload["params"]:
        payload["params"]["model"] = model.name
        strategist.dump_json(raw, payload)
    return outcome("ready" if segments else "no_segments", engine="whisper-cli", model=model.name,
                   model_sha256=strategist.sha256(model), language=language, wall_seconds=round(monotonic() - start, 3),
                   raw=describe(root, raw), segments=segments)


def attempt(function, *args):
    try:
        return function(*args)
    except (MediaError, json.JSONDecodeError) as exc:
        return outcome("failed", str(exc))


def prepare(args):
    start = monotonic()
    source = Path(args.input).resolve()
    suffix = source.suffix.lower()
    supported = IMAGES.keys() | VIDEO.keys() | AUDIO.keys()
    if not source.is_file() or suffix not in supported:
        raise MediaError("Укажите существующий локальный файл поддерживаемого формата.")
    limit = 25 * 1024 * 1024 if suffix in IMAGES else MAX_BYTES
    if not 0 < source.stat().st_size <= limit:
        raise MediaError(f"Допустимый размер файла от 1 до {limit} байт.")
    if suffix in IMAGES:
        if args.whisper_model:
            raise MediaError("У изображения нет звуковой дорожки для распознавания.")
        check_image_signature(source)
    root = Path(args.output).resolve()
    root.mkdir(parents=True)
    original = root / f"original{suffix}"
    shutil.copyfile(source, original)
    manifest = {"schema": SCHEMA, "source_name": source.name, "original": describe(root, original),
                "kind": "image" if suffix in IMAGES else "video" if suffix in VIDEO else "audio",
                "origin": args.origin, "network_used": False}
    if suffix in IMAGES:
        manifest["image"] = outcome("ready", locator="image:1", details="Подготовлены исходные байты для просмотра.")
    else:
        prepare_recording(root, manifest, original, suffix, args)
    manifest["wall_seconds"] = round(monotonic() - start, 3)
    strategist.dump_json(root / "manifest.json", manifest)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    unavailable_requested = any(isinstance(value, dict) and value.get("status") in {"failed", "unavailable"}
                                for value in manifest.values())
    return 2 if unavailable_requested else 0


def prepare_recording(root, manifest, original, suffix, args):
    video = suffix in VIDEO
    media_args = media_input(suffix, original)
    missing = [name for name in ("ffmpeg", "ffprobe") if not shutil.which(name)]
    if missing:
        problem = outcome("unavailable", "Установите " + " и ".join(missing) + ".")
    else:
        try:
            payload, duration = probe(media_args)
            problem = None
        except (MediaError, json.JSONDecodeError) as exc:
            problem = outcome("failed", str(exc))
    if problem:
        if video:
            manifest["frames"] = problem
        manifest["audio"] = problem
    else:
        manifest["duration_seconds"] = duration
        if video:
            manifest["frames"] = attempt(sample_video, root, media_args, first_stream(payload, "video"), duration, args.frames)
        manifest["audio"] = attempt(extract_audio, root, media_args, first_stream(payload, "audio"), duration)
    manifest["transcript"] = attempt(transcribe, root, manifest["audio"], args.whisper_model, args.language)


def evidence(root, manifest):
    original = verified_path(root, manifest["original"])
    records, gaps = [], []
    if manifest["kind"] == "image":
        records.append(("image:1", "Исходное изображение. Откройте сохранённый оригинал."))
        gaps.append("Пиксели требуют просмотра. Содержание изображения автоматически не проверялось.")
    for item in manifest.get("frames", {}).get("items", []):
        verified_path(root, item)
        records.append((item["locator"], f"Видеокадр {item['path']}, PTS {item['source_seconds']} с от начала контейнера."))
    if manifest.get("frames", {}).get("status") == "ready":
        gaps.append("Сохранена выборка кадров. Промежутки требуют проверки по оригиналу.")
    audio = manifest.get("audio", {})
    if audio.get("status") == "ready":
        verified_path(root, audio["file"])
        records.append(("audio:track", "Отдельный WAV. Слушайте дорожку для проверки расшифровки."))
    transcript = manifest.get("transcript", {})
    if "raw" in transcript:
        verified_path(root, transcript["raw"])
    for row in transcript.get("segments", []):
        records.append((row["locator"], "Автоматическое распознавание, проверьте на слух — " + row["text"]))
    if any("model_end_ms" in row for row in transcript.get("segments", [])):
        gaps.append("Конец одного или нескольких интервалов Whisper выходит за длительность WAV. В адресах указан конец дорожки.")
    for key in ("frames", "audio", "transcript"):
        item = manifest.get(key)
        if item and item["status"] != "ready":
            gaps.append(f"{key} — {item['status']}. {item.get('reason', '')}".strip())
    return original, records, gaps


def ingest(args):
    root = strategist.project_root(args.project)
    bundle, manifest = load_bundle(args.bundle)
    if not bundle.is_relative_to(root / "sources" / "media") or bundle == root / "sources" / "media":
        raise MediaError("Сначала подготовьте пакет в PROJECT/sources/media/<имя>.")
    original, records, gaps = evidence(bundle, manifest)
    index_path = root / "sources" / "index.json"
    staging = root / "sources" / ".staging"
    extract_dir = root / "sources" / "extracts"
    original_dir = root / "sources" / "originals"
    if any(not item.resolve().is_relative_to(root) for item in (index_path, staging, extract_dir, original_dir)):
        raise MediaError("Пути реестра источников выходят за пределы кейса.")
    if list(staging.glob("*.pending.json")):
        raise MediaError("Сначала разберите незавершённый импорт через strategist.py ingest-recover.")
    index = strategist.load_json(index_path, None)
    if not isinstance(index, list) or any(not isinstance(entry, dict) for entry in index):
        raise MediaError("Нужен действующий реестр sources/index.json.")
    bundle_path = (bundle / "manifest.json").relative_to(root).as_posix()
    if any(entry.get("media_manifest") == bundle_path for entry in index):
        raise MediaError("Медиапакет уже зарегистрирован.")
    source_id = strategist.next_id(strategist.all_source_ids(root, index), "S")
    staging.mkdir(parents=True, exist_ok=True)
    extract_dir.mkdir(parents=True, exist_ok=True)
    original_dir.mkdir(parents=True, exist_ok=True)
    stage_source = staging / f"{source_id}.source"
    stage_extract = staging / f"{source_id}.extract.md"
    final_extract = extract_dir / f"{source_id}.md"
    stored = (original_dir / f"{source_id}__{original.name}").relative_to(root).as_posix()
    shutil.copyfile(original, stage_source)
    strategist.atomic_text(stage_extract, strategist.render_extract(source_id, records, gaps))
    entry = {
        "source_id": source_id, "kind": manifest["kind"], "title": args.title or manifest["source_name"],
        "origin": bundle_path, "stored_path": stored, "extract_path": final_extract.relative_to(root).as_posix(),
        "sha256": manifest["original"]["sha256"], "extract_sha256": strategist.sha256(stage_extract),
        "retrieved_at": strategist.now(), "permission": manifest["origin"], "synthetic": manifest["origin"] == "synthetic",
        "record_count": len(records), "gaps": gaps, "status": "active", "media_manifest": bundle_path,
        "media_manifest_sha256": strategist.sha256(bundle / "manifest.json"),
    }
    # Общий recovery управляет копией оригинала. Discard сохраняет медиапакет.
    pending = {"source_id": source_id, "entry": entry, "created_at": strategist.now(),
               "stage_source": stage_source.relative_to(root).as_posix(), "final_source": stored,
               "stage_extract": stage_extract.relative_to(root).as_posix(), "final_extract": entry["extract_path"]}
    strategist.dump_json(staging / f"{source_id}.pending.json", pending)
    strategist.command_ingest_recover(SimpleNamespace(project=str(root), source_id=source_id, mode="complete"))
    print(f"Медиапакет зарегистрирован как {source_id}.")
    return 0


def check(args):
    root, manifest = load_bundle(args.bundle)
    evidence(root, manifest)
    if args.project:
        project = strategist.project_root(args.project)
        path = root / "manifest.json"
        if not path.is_relative_to(project):
            raise MediaError("Медиапакет находится вне кейса.")
        entries = [entry for entry in strategist.load_json(project / "sources" / "index.json", [])
                   if entry.get("media_manifest") == path.relative_to(project).as_posix()]
        if len(entries) != 1 or entries[0].get("media_manifest_sha256") != strategist.sha256(path):
            raise MediaError("Опись отсутствует в реестре кейса или изменилась после регистрации.")
        verified_path(project, dict(manifest["original"], path=entries[0]["stored_path"]))
    print("Совпали размеры и SHA-256 оригинала и производных, перечисленных в manifest.json.")
    return 0


def doctor(_args):
    print(json.dumps({name: shutil.which(name) for name in ("ffmpeg", "ffprobe", "whisper-cli", "codex")},
                     ensure_ascii=False, indent=2))
    return 0


def frame_count(raw):
    count = int(raw)
    if not 1 <= count <= 12:
        raise argparse.ArgumentTypeError("допустимо от 1 до 12 кадров")
    return count


def language_code(raw):
    if raw != "auto" and not re.fullmatch(r"[a-z]{2}", raw):
        raise argparse.ArgumentTypeError("нужен двухбуквенный код языка или auto")
    return raw


def parser():
    cli = argparse.ArgumentParser(description=__doc__)
    commands = cli.add_subparsers(required=True)
    commands.add_parser("doctor", help="Проверить наличие необязательных программ").set_defaults(func=doctor)
    pack = commands.add_parser("prepare", help="Подготовить медиапакет без сети")
    pack.add_argument("input")
    pack.add_argument("--output", required=True, help="Новый каталог")
    pack.add_argument("--origin", required=True, choices=["synthetic", "owner-provided", "open-public", "licensed"])
    pack.add_argument("--frames", type=frame_count, default=4)
    pack.add_argument("--whisper-model", type=Path)
    pack.add_argument("--language", type=language_code, default="auto")
    pack.set_defaults(func=prepare)
    registry = commands.add_parser("ingest", help="Зарегистрировать готовый медиапакет в кейсе")
    registry.add_argument("project")
    registry.add_argument("bundle")
    registry.add_argument("--title")
    registry.set_defaults(func=ingest)
    verify = commands.add_parser("check", help="Сверить медиапакет с его описью")
    verify.add_argument("bundle")
    verify.add_argument("--project", help="Дополнительно сверить с реестром кейса")
    verify.set_defaults(func=check)
    return cli


def main():
    try:
        args = parser().parse_args()
        return args.func(args)
    except (ValueError, OSError, KeyError, TypeError) as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
