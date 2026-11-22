#!/usr/bin/env python3
"""Передать проверенные изображения из медиапакетов в Codex CLI."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from time import monotonic

import media
import strategist

PROMPT = strategist.ROOT / "skills" / "media-ux" / "vision-prompt.md"
MAX_ATTACHMENTS = 12
MAX_ATTACHMENT_BYTES = 25 * 1024 * 1024


def attachments(bundles):
    jobs = []
    for number, bundle in enumerate(bundles, 1):
        root, manifest = media.load_bundle(bundle)
        if manifest["kind"] == "image":
            items = [dict(manifest["original"], locator=manifest["image"]["locator"])]
        else:
            items = manifest.get("frames", {}).get("items", [])
        if not items:
            raise media.MediaError(f"Пакет {number} не содержит изображений или готовых кадров.")
        for item in items:
            path = media.verified_path(root, item)
            media.check_image_signature(path)
            info = dict(item, attachment=len(jobs) + 1, bundle=number)
            jobs.append((path, info))
    if not 1 <= len(jobs) <= MAX_ATTACHMENTS or sum(item["bytes"] for _, item in jobs) > MAX_ATTACHMENT_BYTES:
        raise media.MediaError("За один запуск допустимо 1–12 вложений общим размером до 25 МиБ.")
    return jobs


def usage_from(stdout):
    for line in reversed(stdout.splitlines()):
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(record, dict) and record.get("type") == "turn.completed":
            usage = record.get("usage", {})
            return {key: usage[key] for key in ("input_tokens", "cached_input_tokens", "output_tokens")
                    if isinstance(usage.get(key), int)}
    return {}


def invoke(codex, jobs, args):
    lookup = "\n".join(f"- Вложение {item['attachment']} — пакет {item['bundle']}#{item['locator']}"
                       for _, item in jobs)
    prompt = f"{PROMPT.read_text(encoding='utf-8')}\nВложения в порядке передачи:\n{lookup}\n"
    if args.question:
        prompt += f"\nЗадача от владельца кейса:\n{args.question}\n"
    with tempfile.TemporaryDirectory(prefix="strategist-vision-") as tmp:
        scratch = Path(tmp).resolve()
        cmd = [codex, "exec", "--sandbox", "read-only", "--skip-git-repo-check", "--ephemeral",
               "--ignore-user-config", "--ignore-rules", "--disable", "shell_tool", "--disable", "view_image",
               "--disable", "enable_mcp_apps", "-c", 'web_search="disabled"', "--json"]
        if args.model:
            cmd += ["--model", args.model]
        for path, item in jobs:
            attached = scratch / f"{item['attachment']:02d}{path.suffix}"
            shutil.copyfile(path, attached)
            if strategist.sha256(attached) != item["sha256"]:
                return media.outcome("failed", "Изображение изменилось перед передачей.")
            cmd += ["--image", str(attached)]
        response = scratch / "response.md"
        cmd += ["--output-last-message", str(response), "-"]
        try:
            result = subprocess.run(cmd, cwd=scratch, input=prompt, capture_output=True, text=True,
                                    errors="replace", timeout=args.timeout)
        except subprocess.TimeoutExpired:
            return media.outcome("outcome_unknown", f"Истёк лимит {args.timeout} с. Проверьте квоту до повтора.")
        except OSError as exc:
            return media.outcome("outcome_unknown", f"Codex не завершился штатно: {exc.strerror}.")
        usage = usage_from(result.stdout)
        if result.returncode or not response.is_file() or not response.stat().st_size:
            return media.outcome("outcome_unknown", "Codex не вернул готовый ответ. Проверьте вход и доступ модели.",
                                 exit_code=result.returncode, usage=usage)
        return media.outcome("response_saved", reviewed=False, usage=usage,
                             response=response.read_text(encoding="utf-8"))


def review(args):
    if not args.allow_upload:
        raise media.MediaError("Для передачи изображений в Codex требуется явный флаг --allow-upload.")
    jobs = attachments(args.bundles)
    root = Path(args.output).resolve()
    root.mkdir(parents=True)
    receipt = {"schema": "strategist.media-vision/1.0", "backend": "codex-cli",
               "model_requested": args.model, "question": args.question, "prompt_sha256": strategist.sha256(PROMPT),
               "cost_status": "unknown",
               "attachments": [item for _, item in jobs], "status": "started"}
    receipt_path = root / "receipt.json"
    strategist.dump_json(receipt_path, receipt)
    start = monotonic()
    codex = shutil.which("codex")
    if codex:
        result = invoke(codex, jobs, args)
    else:
        result = media.outcome("unavailable", "Codex CLI отсутствует. Используйте среду с поддержкой изображений.")
    response = result.pop("response", None)
    if response:
        path = root / "review.md"
        strategist.atomic_text(path, response)
        result["review"] = media.describe(root, path)
    receipt.update(result, wall_seconds=round(monotonic() - start, 3))
    strategist.dump_json(receipt_path, receipt)
    print(json.dumps(receipt, ensure_ascii=False, indent=2))
    return 0 if receipt["status"] == "response_saved" else 2


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("bundles", nargs="+")
    cli.add_argument("--output", required=True, help="Новый каталог для ответа и квитанции")
    cli.add_argument("--question")
    cli.add_argument("--model", help="Модель доступная в текущем аккаунте Codex")
    cli.add_argument("--timeout", type=int, default=180)
    cli.add_argument("--allow-upload", action="store_true")
    args = cli.parse_args()
    if not 1 <= args.timeout <= 600:
        cli.error("--timeout должен быть от 1 до 600 с")
    try:
        return review(args)
    except (ValueError, OSError, KeyError, TypeError) as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
