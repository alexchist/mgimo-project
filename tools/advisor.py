"""Plan a Strategist route or dispatch one scoped, read-only advisor turn."""

import argparse
import asyncio
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import tempfile
import time

import advisor_codex


ROOT = Path(__file__).resolve().parents[1]
MAX_TEXT_BYTES = 24_000
MODEL_CHARS = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-:")
EFFORTS = ("low", "medium", "high")
ROUTES = {
    "frame": ("skills/frame-decision/SKILL.md", "Основной агент IDE", "Уточнить развилку и критерий выбора"),
    "research": ("skills/investigate/SKILL.md", "tools/strategist.py ingest", "Извлечь и привязать к источникам"),
    "data": ("skills/analyze-data/SKILL.md", "tools/strategist.py profile и Python", "Пересчитать с явными единицами и знаменателями"),
    "options": ("skills/compare-options/SKILL.md", "Основной агент IDE", "Сравнить варианты и ближайшую альтернативу"),
    "strategy": ("skills/align-strategies/SKILL.md", "Основной агент IDE", "Согласовать пользу продукта и обещание клиенту"),
    "review": ("skills/review-decision/SKILL.md", "Основной агент IDE и tools/strategist.py check", "Проверить смысл и реестры"),
    "resume": ("skills/review-decision/SKILL.md", "tools/strategist.py resume", "Продолжить с подтверждённого состояния"),
    "revision": ("skills/review-decision/SKILL.md", "tools/strategist.py ingest и revise", "Сохранить прежнее основание перед изменениями"),
    "interview": ("skills/interview/SKILL.md", "Интервьюер и человек с согласием", "Восстановить реальные эпизоды"),
    "respondent": ("skills/interview/SKILL.md", advisor_codex.TOOL, "Сгенерировать гипотезу в одной заданной роли"),
    "critic": ("skills/review-decision/challenge.md", advisor_codex.TOOL, "Получить отдельное возражение и различающую проверку"),
    "vision": ("skills/media-ux/SKILL.md", "tools/media_vision.py", "Описать наблюдаемое в разрешённом изображении"),
    "media": ("skills/media-ux/SKILL.md", "tools/media.py", "Выделить кадр или фрагмент с тайм-кодом"),
}
ROLES = {"respondent": "synthetic_respondent", "critic": "model_critique"}
FALLBACK = (
    "Проверьте журнал попытки. Если требуется другой маршрут, явно откройте чистую сессию IDE "
    "с тем же разрешённым пакетом и ролью без инструментов, либо укажите поддерживаемые модель и усилие в новой попытке."
)


def digest(text):
    return sha256(text.encode("utf-8")).hexdigest()


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def encode(data):
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"


def read_text(path, max_bytes=MAX_TEXT_BYTES):
    if not path.is_file():
        raise ValueError(f"Ожидается обычный файл: {path.name}")
    with path.open("rb") as stream:
        raw = stream.read(max_bytes + 1)
    if len(raw) > max_bytes:
        raise ValueError(f"Файл {path.name} длиннее {max_bytes} байт. Выделите фрагмент.")
    content = raw.decode("utf-8")
    if not content.strip():
        raise ValueError(f"Файл {path.name} пуст.")
    return content


def history(args, context_hash):
    if args.previous is None:
        return [], None
    if args.role != "respondent":
        raise ValueError("--previous доступен только в роли respondent.")
    raw = read_text(args.previous, 3 * MAX_TEXT_BYTES)
    previous = json.loads(raw)
    if not isinstance(previous, dict) or (
        previous.get("status"), previous.get("kind"), previous.get("context_sha256"),
    ) != ("succeeded", ROLES["respondent"], context_hash):
        raise ValueError("Предыдущая попытка должна содержать успешный ответ респондента с тем же контекстом.")
    turns = previous.get("turns")
    if not isinstance(turns, list) or not turns or any(
        not isinstance(turn, dict) or set(turn) != {"question", "answer"}
        or any(not isinstance(text, str) or not text.strip() for text in turn.values())
        for turn in turns
    ):
        raise ValueError("Журнал беседы повреждён.")
    return turns, digest(raw)


def finish_record(path, record):
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                     prefix=".advisor-", delete=False) as temporary:
        staged = Path(temporary.name)
        try:
            temporary.write(encode(record))
            temporary.close()
            staged.replace(path)
        finally:
            staged.unlink(missing_ok=True)


def select_model(args):
    profile_hash = None
    settings = {}
    if args.profile is not None:
        raw = read_text(args.profile)
        profile = json.loads(raw)
        if not isinstance(profile, dict) or (profile.keys() - ROLES.keys()):
            raise ValueError("Профиль должен быть JSON-объектом с ключами respondent и/или critic.")
        settings = profile.get(args.role)
        if not isinstance(settings, dict) or settings.keys() != {"model", "effort"}:
            raise ValueError(f"В профиле для роли {args.role} нужны поля model и effort.")
        try:
            model_id(settings["model"])
        except argparse.ArgumentTypeError as error:
            raise ValueError(str(error)) from error
        if settings["effort"] not in EFFORTS:
            raise ValueError("В профиле effort должен быть low, medium или high.")
        profile_hash = digest(raw)

    model = args.model or settings.get("model")
    effort = args.effort or settings.get("effort")
    if model is None or effort is None:
        raise ValueError("Передайте --model и --effort или явно укажите --profile.")
    selection = {"model": "flag" if args.model else "profile",
                 "effort": "flag" if args.effort else "profile", "profile_sha256": profile_hash}
    return model, effort, selection


def run(args):
    model, effort, selection = select_model(args)
    context = read_text(args.context)
    question = read_text(args.question)
    context_hash = digest(context)
    turns, previous_hash = history(args, context_hash)
    instructions = read_text(ROOT / "prompts" / f"advisor-{args.role}.md")
    packet = encode({"context": context, "previous_turns": turns, "question": question})
    if len(packet.encode("utf-8")) > MAX_TEXT_BYTES:
        raise ValueError(f"Пакет длиннее {MAX_TEXT_BYTES} байт. Сузьте запрос или начните отдельное интервью.")

    record = {
        "status": "dispatch_intent", "kind": ROLES[args.role], "tool": advisor_codex.TOOL,
        "requested_model": model, "requested_effort": effort, "selection": selection,
        "provider": None, "auth_route": None, "cli_model": None, "cli_effort": None,
        "cli_version": None, "turn_requested": False, "cost_status": "unknown", "cost_amount": None,
        "started_at": utc_now(), "finished_at": None, "elapsed_seconds": None,
        "instructions_sha256": digest(instructions), "context_sha256": context_hash,
        "packet_sha256": digest(packet), "previous_sha256": previous_hash, "turns": turns,
        "question": question, "reason": None,
    }
    # Reserving the path before any call makes an interrupted attempt visible.
    with args.out.open("x", encoding="utf-8") as handle:
        handle.write(encode(record))

    started = time.monotonic()
    try:
        binary = shutil.which("codex")
        if binary is None:
            raise advisor_codex.RouteError("codex_not_found")
        answer = asyncio.run(advisor_codex.run(str(Path(binary).resolve()), instructions, packet, record, args.timeout))
        record["turns"] = [*turns, {"question": question, "answer": answer}]
        record["status"] = "succeeded"
    except advisor_codex.RouteError as error:
        record.update(status=error.status, reason=str(error))
    except KeyboardInterrupt:
        record.update(status="outcome_unknown" if record["turn_requested"] else "failed", reason="interrupted")
    except (ValueError, TypeError, KeyError, AttributeError, OSError) as error:
        record.update(status="outcome_unknown" if record["turn_requested"] else "failed", reason=type(error).__name__)
    finally:
        record.update(finished_at=utc_now(), elapsed_seconds=round(time.monotonic() - started, 3))
        finish_record(args.out, record)
    print(encode({key: record[key] for key in ("status", "tool", "cli_model", "elapsed_seconds", "cost_status", "reason")}), end="")
    if record["status"] == "succeeded":
        return 0
    print(FALLBACK)
    return 1


def route(capability):
    skill, tool, goal = ROUTES[capability]
    choice = {"capability": capability, "skill": skill, "tool": tool, "goal": goal}
    if capability in ROLES:
        choice.update(
            executable="codex", installed=shutil.which("codex") is not None,
            model_to_consider="gpt-5.6-sol" if capability == "respondent" else "gpt-6.2-astra",
            effort_to_consider="low" if capability == "respondent" else "medium",
            cost_status="unknown", fallback=FALLBACK,
        )
    elif capability == "vision":
        choice["input"] = "Изображение или кадр с исходным локатором как явное вложение."
        choice["fallback"] = "Явно прикрепите изображение через CLI с --image либо используйте проверенное описание автора."
    print(encode(choice), end="")
    return 0


def model_id(value):
    if not isinstance(value, str) or not value or len(value) > 100 or any(char not in MODEL_CHARS for char in value):
        raise argparse.ArgumentTypeError("Укажите идентификатор модели, поддерживаемой вашим Codex.")
    return value


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    planner = subparsers.add_parser("route", help="Подобрать маршрут без вызова модели.")
    planner.add_argument("capability", choices=ROUTES)
    job = subparsers.add_parser("run", help="Выполнить один вызов выбранной роли.")
    job.add_argument("--role", choices=ROLES, required=True)
    job.add_argument("--via", choices=["codex"], required=True)
    job.add_argument("--profile", type=Path, help="Явно выбранный UTF-8 JSON с model и effort по ролям.")
    job.add_argument("--model", type=model_id)
    job.add_argument("--effort", choices=EFFORTS)
    job.add_argument("--context", type=Path, required=True)
    job.add_argument("--question", type=Path, required=True)
    job.add_argument("--previous", type=Path)
    job.add_argument("--out", type=Path, required=True)
    job.add_argument("--timeout", type=int, default=120, help="Секунды ожидания CLI.")
    args = parser.parse_args(argv)
    if args.command == "route":
        return route(args.capability)
    if args.timeout <= 0:
        job.error("--timeout должен быть больше нуля.")
    try:
        return run(args)
    except FileExistsError:
        job.error("Файл --out уже есть. Проверьте прежнюю попытку перед новым вызовом.")
    except (OSError, ValueError) as error:
        job.error(str(error))


if __name__ == "__main__":
    raise SystemExit(main())
