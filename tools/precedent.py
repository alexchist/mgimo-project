#!/usr/bin/env python3
"""Curated, local precedents shared by cases in one repository checkout."""

from __future__ import annotations

import argparse
import contextlib
import csv
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
import tempfile
from typing import Any, Iterator


STORE_VERSION = 1
PORTFOLIO_DIR = ".portfolio"
STORE_NAME = "precedents.json"
LOCK_NAME = ".precedents.lock"
REFERENCE_RE = re.compile(r"^(?P<kind>[CD])-[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
ID_RE = re.compile(r"^P-(\d{4,})$")


class PrecedentError(Exception):
    """A user-facing, expected CLI error."""


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def split_refs(value: str) -> list[str]:
    return [item.strip() for item in value.split(";") if item.strip()]


def safe_text(value: str, label: str, maximum: int) -> str:
    value = value.strip()
    if not value:
        raise PrecedentError(f"{label} не может быть пустым")
    if len(value) > maximum:
        raise PrecedentError(f"{label} длиннее {maximum} символов; сохраните только короткий урок")
    return value


def ensure_no_symlinks(path: Path, base: Path, *, require_final: bool = True) -> None:
    """Reject symlinks in every component below base and enforce containment."""
    try:
        relative = path.relative_to(base)
    except ValueError as exc:
        raise PrecedentError(f"путь вне рабочей копии: {path}") from exc
    current = base
    for index, part in enumerate(relative.parts):
        current = current / part
        try:
            mode = current.lstat().st_mode
        except FileNotFoundError:
            if require_final or index < len(relative.parts) - 1:
                raise PrecedentError(f"путь недоступен: {current.relative_to(base)}")
            return
        if stat.S_ISLNK(mode):
            raise PrecedentError(f"символические ссылки запрещены: {current.relative_to(base)}")


def resolve_case(root: Path, case_argument: str) -> tuple[Path, str]:
    supplied = Path(case_argument)
    if supplied.is_absolute():
        raise PrecedentError("кейс должен быть относительным путём под projects/")
    parts = supplied.parts
    if parts and parts[0] == "projects":
        parts = parts[1:]
    if not parts or any(part in {"", ".", ".."} for part in parts):
        raise PrecedentError("кейс должен быть непустым относительным путём под projects/")
    projects = root / "projects"
    ensure_no_symlinks(projects, root)
    case_path = projects.joinpath(*parts)
    ensure_no_symlinks(case_path, root)
    if not case_path.is_dir():
        raise PrecedentError(f"кейс не является каталогом: projects/{'/'.join(parts)}")
    projects_real = projects.resolve(strict=True)
    case_real = case_path.resolve(strict=True)
    try:
        case_real.relative_to(projects_real)
    except ValueError as exc:
        raise PrecedentError("кейс выходит за пределы projects/") from exc
    return case_path, case_path.relative_to(root).as_posix()


def registry_file(root: Path, case_path: Path, relative: str) -> Path:
    path = case_path / relative
    ensure_no_symlinks(path, root)
    if not path.is_file():
        raise PrecedentError(f"реестр недоступен: {path.relative_to(root)}")
    return path


def read_registry(root: Path, case_path: Path, relative: str, id_field: str) -> dict[str, dict[str, str]]:
    path = registry_file(root, case_path, relative)
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle, strict=True)
            if reader.fieldnames is None:
                raise PrecedentError(f"в реестре нет заголовка: {path.relative_to(root)}")
            if len(set(reader.fieldnames)) != len(reader.fieldnames):
                raise PrecedentError(f"в реестре повторяются заголовки: {path.relative_to(root)}")
            if id_field not in reader.fieldnames:
                raise PrecedentError(f"в реестре нет колонки {id_field}: {path.relative_to(root)}")
            rows: dict[str, dict[str, str]] = {}
            for number, row in enumerate(reader, start=2):
                if None in row or None in row.values():
                    raise PrecedentError(f"неверная ширина строки в {path.relative_to(root)}:{number}")
                row_id = (row.get(id_field) or "").strip()
                if not row_id:
                    continue
                if row_id in rows:
                    raise PrecedentError(f"повторяющийся {id_field}={row_id} в {path.relative_to(root)}")
                rows[row_id] = {key: value or "" for key, value in row.items() if key is not None}
            return rows
    except UnicodeError as exc:
        raise PrecedentError(f"реестр не является UTF-8 CSV: {path.relative_to(root)}") from exc
    except csv.Error as exc:
        raise PrecedentError(f"ошибка CSV в {path.relative_to(root)}: {exc}") from exc


def require_columns(row: dict[str, str], columns: tuple[str, ...], registry: str) -> None:
    missing = [column for column in columns if column not in row]
    if missing:
        raise PrecedentError(f"в {registry} нет колонок: {', '.join(missing)}")


def row_digest(row: dict[str, str]) -> str:
    canonical = json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def node(registry: str, ref: str, row: dict[str, str]) -> dict[str, str]:
    return {"registry": registry, "ref": ref, "digest": row_digest(row)}


def source_snapshot(root: Path, case_path: Path, ref: str) -> dict[str, Any]:
    match = REFERENCE_RE.fullmatch(ref)
    if not match:
        raise PrecedentError("--ref должен иметь вид C-... или D-...")

    conclusions: dict[str, dict[str, str]] | None = None
    claims: dict[str, dict[str, str]] | None = None
    nodes: list[dict[str, str]] = []
    warnings: list[str] = []

    def add_claims(conclusion_row: dict[str, str]) -> None:
        nonlocal claims
        require_columns(
            conclusion_row,
            ("conclusion_id", "evidence_ids", "status", "review_needed"),
            "evidence/conclusions.csv",
        )
        if conclusion_row["status"].strip().lower() != "active":
            warnings.append(f"{conclusion_row['conclusion_id']}: status={conclusion_row['status'] or '(empty)'}")
        if conclusion_row["review_needed"].strip().lower() not in {"", "no", "false", "0"}:
            warnings.append(
                f"{conclusion_row['conclusion_id']}: review_needed={conclusion_row['review_needed']}"
            )
        evidence_ids = split_refs(conclusion_row["evidence_ids"])
        if evidence_ids:
            if claims is None:
                claims = read_registry(root, case_path, "evidence/claims.csv", "claim_id")
            for evidence_id in evidence_ids:
                evidence = claims.get(evidence_id)
                if evidence is None:
                    raise PrecedentError(f"зависимость {evidence_id} не найдена в evidence/claims.csv")
                require_columns(evidence, ("claim_id", "status"), "evidence/claims.csv")
                nodes.append(node("evidence/claims.csv", evidence_id, evidence))
                if evidence["status"].strip().lower() != "active":
                    warnings.append(f"{evidence_id}: status={evidence['status'] or '(empty)'}")

    if match.group("kind") == "C":
        conclusions = read_registry(root, case_path, "evidence/conclusions.csv", "conclusion_id")
        conclusion = conclusions.get(ref)
        if conclusion is None:
            raise PrecedentError(f"строка {ref} не найдена в evidence/conclusions.csv")
        require_columns(conclusion, ("conclusion_id", "status"), "evidence/conclusions.csv")
        nodes.append(node("evidence/conclusions.csv", ref, conclusion))
        add_claims(conclusion)
        metadata = {
            "kind": "conclusion",
            "kind_label": "вывод",
            "status": conclusion["status"],
            "decision_kind": None,
            "recorded_at": None,
        }
    else:
        decisions = read_registry(root, case_path, "decisions/decisions.csv", "decision_id")
        decision = decisions.get(ref)
        if decision is None:
            raise PrecedentError(f"строка {ref} не найдена в decisions/decisions.csv")
        require_columns(
            decision,
            ("decision_id", "recorded_at", "decision_kind", "status", "conclusion_ids"),
            "decisions/decisions.csv",
        )
        nodes.append(node("decisions/decisions.csv", ref, decision))
        conclusion_ids = split_refs(decision["conclusion_ids"])
        if conclusion_ids:
            conclusions = read_registry(root, case_path, "evidence/conclusions.csv", "conclusion_id")
            for conclusion_id in conclusion_ids:
                conclusion = conclusions.get(conclusion_id)
                if conclusion is None:
                    raise PrecedentError(
                        f"зависимость {conclusion_id} не найдена в evidence/conclusions.csv"
                    )
                nodes.append(node("evidence/conclusions.csv", conclusion_id, conclusion))
                add_claims(conclusion)
        metadata = {
            "kind": "decision",
            "kind_label": "решение",
            "status": decision["status"],
            "decision_kind": decision["decision_kind"],
            "recorded_at": decision["recorded_at"] or None,
        }

    nodes.sort(key=lambda item: (item["registry"], item["ref"]))
    combined = json.dumps(nodes, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return {
        "metadata": metadata,
        "nodes": nodes,
        "digest": "sha256:" + hashlib.sha256(combined.encode("utf-8")).hexdigest(),
        "warnings": sorted(set(warnings)),
    }


def portfolio_paths(root: Path) -> tuple[Path, Path, Path]:
    directory = root / PORTFOLIO_DIR
    return directory, directory / STORE_NAME, directory / LOCK_NAME


def ensure_portfolio(root: Path) -> tuple[Path, Path, Path]:
    directory, store, lock = portfolio_paths(root)
    if directory.exists() or directory.is_symlink():
        ensure_no_symlinks(directory, root)
        if not directory.is_dir():
            raise PrecedentError(f"{PORTFOLIO_DIR} не является каталогом")
    else:
        directory.mkdir(mode=0o700)
    for path in (store, lock):
        if path.exists() or path.is_symlink():
            ensure_no_symlinks(path, root)
            if not path.is_file():
                raise PrecedentError(f"{path.relative_to(root)} не является обычным файлом")
    return directory, store, lock


def empty_store() -> dict[str, Any]:
    return {"schema_version": STORE_VERSION, "items": []}


def validate_store(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict) or data.get("schema_version") != STORE_VERSION:
        raise PrecedentError("неподдерживаемая или повреждённая .portfolio/precedents.json")
    items = data.get("items")
    if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
        raise PrecedentError("повреждён список precedents в .portfolio/precedents.json")
    return data


def load_store(root: Path, *, absent_ok: bool = True) -> dict[str, Any]:
    directory, store, _ = portfolio_paths(root)
    if directory.exists() or directory.is_symlink():
        ensure_no_symlinks(directory, root)
        if not directory.is_dir():
            raise PrecedentError(f"{PORTFOLIO_DIR} не является каталогом")
    elif absent_ok:
        return empty_store()
    else:
        raise PrecedentError("межпроектная память ещё не создана")
    if not store.exists() and not store.is_symlink():
        if absent_ok:
            return empty_store()
        raise PrecedentError("межпроектная память ещё не создана")
    ensure_no_symlinks(store.parent, root)
    ensure_no_symlinks(store, root)
    if not store.is_file():
        raise PrecedentError(f"{store.relative_to(root)} не является обычным файлом")
    try:
        with store.open("r", encoding="utf-8") as handle:
            return validate_store(json.load(handle))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise PrecedentError("повреждён JSON в .portfolio/precedents.json") from exc


@contextlib.contextmanager
def writer_lock(root: Path) -> Iterator[Path]:
    _, store, lock = ensure_portfolio(root)
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise PrecedentError(f"Запись занята: {lock.name}. Если предыдущий writer прерван, проверьте реестр и снимите оставшуюся блокировку вручную.") from exc
    try:
        yield store
    finally:
        os.close(descriptor)
        lock.unlink()


def atomic_save(directory: Path, store: Path, data: dict[str, Any]) -> None:
    payload = (json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    descriptor, temporary_name = tempfile.mkstemp(prefix=".precedents-", suffix=".tmp", dir=directory)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, store)
    finally:
        if temporary.exists():
            temporary.unlink()


def next_id(items: list[dict[str, Any]]) -> str:
    numbers = []
    for item in items:
        match = ID_RE.fullmatch(str(item.get("id", "")))
        if match:
            numbers.append(int(match.group(1)))
    return f"P-{max(numbers, default=0) + 1:04d}"


def public_item(item: dict[str, Any], root: Path, checked_at: str) -> dict[str, Any]:
    result = {
        "id": item.get("id"),
        "source_ref": f"{item.get('case')}#{item.get('ref')}",
        "case": item.get("case"),
        "ref": item.get("ref"),
        "remembered_at": item.get("remembered_at"),
        "topic": item.get("topic"),
        "note": item.get("note"),
        "when": item.get("when"),
        "source_at_remember": item.get("source_at_remember"),
        "retired": bool(item.get("retired")),
        "retired_at": item.get("retired_at"),
        "retire_reason": item.get("retire_reason"),
    }
    try:
        case_path, canonical = resolve_case(root, str(item.get("case", "")))
        if canonical != item.get("case"):
            raise PrecedentError("сохранённый путь кейса неканоничен")
        current = source_snapshot(root, case_path, str(item.get("ref", "")))
    except (PrecedentError, OSError) as exc:
        result["source_now"] = None
        result["source_check"] = {
            "state": "unavailable",
            "label": "источник или его основание недоступны",
            "checked_at": checked_at,
            "semantic_currentness_assessed": False,
            "details": str(exc),
        }
        return result

    result["source_now"] = current["metadata"]
    if current["digest"] != item.get("snapshot_digest"):
        state = "changed"
        label = "источник или его основание изменились — требуется перепроверка"
    elif current["warnings"]:
        state = "requires_recheck"
        label = "снимок совпадает, но основание помечено для перепроверки"
    else:
        state = "matches"
        label = "источник совпадает с запомненным снимком"
    result["source_check"] = {
        "state": state,
        "label": label,
        "checked_at": checked_at,
        "semantic_currentness_assessed": False,
        "details": current["warnings"],
    }
    return result


def command_remember(args: argparse.Namespace, root: Path) -> dict[str, Any]:
    topic = safe_text(args.topic, "--topic", 120)
    note = safe_text(args.note, "--note", 1000)
    when = safe_text(args.when, "--when", 500)
    ref = args.ref.strip()
    case_path, case_name = resolve_case(root, args.case)
    snapshot = source_snapshot(root, case_path, ref)
    remembered_at = utc_now()
    with writer_lock(root) as store_path:
        data = load_store(root)
        items = data["items"]
        item = {
            "id": next_id(items),
            "case": case_name,
            "ref": ref,
            "remembered_at": remembered_at,
            "topic": topic,
            "note": note,
            "when": when,
            "source_at_remember": snapshot["metadata"],
            "snapshot_digest": snapshot["digest"],
            "snapshot_nodes": snapshot["nodes"],
            "retired": False,
            "retired_at": None,
            "retire_reason": None,
        }
        items.append(item)
        atomic_save(store_path.parent, store_path, data)
    return public_item(item, root, remembered_at)


def searchable_text(item: dict[str, Any]) -> str:
    fields = (
        item.get("id"),
        item.get("case"),
        item.get("ref"),
        item.get("topic"),
        item.get("note"),
        item.get("when"),
        item.get("retire_reason"),
    )
    return "\n".join(str(value) for value in fields if value is not None).casefold()


def command_find(args: argparse.Namespace, root: Path) -> dict[str, Any]:
    data = load_store(root)
    terms = [term.casefold() for term in args.words if term.strip()]
    selected = []
    checked_at = utc_now()
    for item in data["items"]:
        if item.get("retired") and not args.include_retired:
            continue
        haystack = searchable_text(item)
        if all(term in haystack for term in terms):
            selected.append(public_item(item, root, checked_at))
    result = {
        "query": args.words,
        "include_retired": args.include_retired,
        "items": selected,
        "notice": "Проверяется совпадение сохранённых строк, а не смысловая актуальность урока.",
    }
    if terms and not selected:
        result["hint"] = "Буквально не найдено. Поиск по смыслу: python3 tools/recall.py precedents \"<ситуация своими словами>\""
    return result


def command_retire(args: argparse.Namespace, root: Path) -> dict[str, Any]:
    reason = safe_text(args.reason, "--reason", 500)
    retired_at = utc_now()
    with writer_lock(root) as store_path:
        data = load_store(root, absent_ok=False)
        matches = [item for item in data["items"] if item.get("id") == args.id]
        if not matches:
            raise PrecedentError(f"precedent {args.id} не найден")
        item = matches[0]
        if item.get("retired"):
            raise PrecedentError(f"precedent {args.id} уже отозван")
        item["retired"] = True
        item["retired_at"] = retired_at
        item["retire_reason"] = reason
        atomic_save(store_path.parent, store_path, data)
    return public_item(item, root, retired_at)


def build_parser() -> argparse.ArgumentParser:
    description = (
        "Локальная, сознательно отобранная память одной команды между кейсами под projects/. "
        "Данные пишутся в .portfolio/ внутри текущей рабочей копии; это приватный output по соглашению, "
        "но НЕ граница доступа ОС и не замена filesystem sandbox."
    )
    parser = argparse.ArgumentParser(description=description)
    subparsers = parser.add_subparsers(dest="command", required=True)

    remember = subparsers.add_parser("remember", help="запомнить короткий урок из C-* или D-*")
    remember.add_argument("case", help="slug или путь projects/<case>")
    remember.add_argument("--ref", required=True, help="C-... или D-...")
    remember.add_argument("--topic", required=True, help="короткая тема (до 120 символов)")
    remember.add_argument("--note", required=True, help="отобранный смысл, не сырой артефакт")
    remember.add_argument("--when", required=True, help="контекст применения или условие пересмотра")

    find = subparsers.add_parser("find", help="найти доступные precedents; без слов показать все")
    find.add_argument("words", nargs="*", help="все слова должны встретиться в записи")
    find.add_argument(
        "--include-retired",
        action="store_true",
        help="включить отозванные записи и историческую причину",
    )

    retire = subparsers.add_parser("retire", help="отозвать precedent без удаления истории")
    retire.add_argument("id", help="например P-0001")
    retire.add_argument("--reason", required=True, help="почему запись больше не предлагать")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    root = Path.cwd().resolve()
    try:
        if args.command == "remember":
            output = command_remember(args, root)
        elif args.command == "find":
            output = command_find(args, root)
        else:
            output = command_retire(args, root)
    except (PrecedentError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
