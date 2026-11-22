#!/usr/bin/env python3
"""Select one Strategist case and read only regular files inside it.

Used by the read-only MCP server and the recall CLI. A case is a directory
``projects/<slug>`` or ``examples/<slug>`` below the repository root that holds
``project.json``. Symbolic links and special files anywhere in the case tree
are refused instead of followed. This is a guard against accidental exposure in
a local checkout, not an operating-system sandbox.
"""

from __future__ import annotations

import csv
import io
import os
from pathlib import Path
import stat

ALLOWED_PARENTS = ("projects", "examples")
MAX_TREE_ENTRIES = 20000
MAX_FILE_BYTES = 8 * 1024 * 1024


class ScopeError(Exception):
    """The case cannot be used safely; the message is shown to the caller."""


def _lstat(path: Path) -> os.stat_result | None:
    try:
        return path.lstat()
    except FileNotFoundError:
        return None


def no_symlink_components(path: Path, base: Path) -> None:
    """Every component from ``base`` down to ``path`` must exist and not be a symlink."""
    try:
        relative = path.relative_to(base)
    except ValueError as exc:
        raise ScopeError("путь вне рабочей копии") from exc
    current = base
    for part in relative.parts:
        current = current / part
        info = _lstat(current)
        if info is None:
            raise ScopeError(f"путь недоступен: {current.relative_to(base).as_posix()}")
        if stat.S_ISLNK(info.st_mode):
            raise ScopeError(f"символические ссылки запрещены: {current.relative_to(base).as_posix()}")


def select_case(root: Path, case_argument: str) -> tuple[Path, str]:
    """Return (absolute case directory, canonical relative name) or raise ScopeError."""
    root = root.resolve(strict=True)
    supplied = Path(case_argument)
    if not case_argument.strip() or supplied.is_absolute():
        raise ScopeError("кейс задаётся относительным путём: projects/<slug> или examples/<slug>")
    parts = supplied.parts
    if any(part in {"", ".", ".."} for part in parts):
        raise ScopeError("в пути кейса нельзя использовать '.' или '..'")
    if len(parts) < 2 or parts[0] not in ALLOWED_PARENTS:
        raise ScopeError("кейс должен лежать в projects/<slug> или examples/<slug>")
    case = root.joinpath(*parts)
    no_symlink_components(case, root)
    if not stat.S_ISDIR(case.lstat().st_mode):
        raise ScopeError(f"кейс не является каталогом: {supplied.as_posix()}")
    marker = _lstat(case / "project.json")
    if marker is None or not stat.S_ISREG(marker.st_mode):
        raise ScopeError(f"в кейсе нет обычного файла project.json: {supplied.as_posix()}")
    try:
        case.resolve(strict=True).relative_to(root)
    except ValueError as exc:
        raise ScopeError("кейс выходит за пределы рабочей копии") from exc
    return case, Path(*parts).as_posix()


def scan_case(case: Path) -> int:
    """Refuse the whole case if any symlink or special file is present; return entry count."""
    offenders: list[str] = []
    count = 0
    stack = [case]
    while stack:
        directory = stack.pop()
        with os.scandir(directory) as entries:
            for entry in entries:
                count += 1
                if count > MAX_TREE_ENTRIES:
                    raise ScopeError(f"в кейсе больше {MAX_TREE_ENTRIES} файлов; сузьте рабочую папку")
                relative = Path(entry.path).relative_to(case).as_posix()
                if entry.is_symlink():
                    offenders.append(f"{relative} (символическая ссылка)")
                elif entry.is_dir(follow_symlinks=False):
                    stack.append(Path(entry.path))
                elif not entry.is_file(follow_symlinks=False):
                    offenders.append(f"{relative} (не обычный файл)")
    if offenders:
        shown = ", ".join(sorted(offenders)[:5])
        more = f" и ещё {len(offenders) - 5}" if len(offenders) > 5 else ""
        raise ScopeError(f"кейс содержит небезопасные элементы: {shown}{more}. Инструменты не читают такой кейс.")
    return count


def read_bytes(case: Path, relative: str, *, limit: int = MAX_FILE_BYTES) -> bytes:
    """Read a regular file below ``case`` without following a final symlink."""
    candidate = Path(relative)
    if candidate.is_absolute() or any(part in {"", ".", ".."} for part in candidate.parts):
        raise ScopeError(f"недопустимый путь внутри кейса: {relative!r}")
    path = case.joinpath(*candidate.parts)
    no_symlink_components(path, case)
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise ScopeError(f"файл недоступен: {candidate.as_posix()}") from exc
    with os.fdopen(descriptor, "rb") as handle:
        info = os.fstat(handle.fileno())
        if not stat.S_ISREG(info.st_mode):
            raise ScopeError(f"не обычный файл: {candidate.as_posix()}")
        if info.st_size > limit:
            raise ScopeError(f"файл больше {limit} байт: {candidate.as_posix()}")
        return handle.read(limit + 1)[:limit]


def read_text(case: Path, relative: str, *, limit: int = MAX_FILE_BYTES) -> str:
    try:
        return read_bytes(case, relative, limit=limit).decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ScopeError(f"файл не в UTF-8: {relative}") from exc


def read_registry(case: Path, relative: str, id_field: str) -> list[dict[str, str]]:
    """Read a CSV registry strictly: header present, id column present, rectangular rows."""
    raw = read_text(case, relative)
    reader = csv.DictReader(io.StringIO(raw, newline=""), strict=True)
    try:
        rows = list(reader)
    except csv.Error as exc:
        raise ScopeError(f"ошибка CSV в {relative}: {exc}") from exc
    headers = reader.fieldnames or []
    if id_field not in headers or len(set(headers)) != len(headers):
        raise ScopeError(f"{relative}: нет колонки {id_field} или повторяются заголовки")
    for number, row in enumerate(rows, start=2):
        if None in row or None in row.values():
            raise ScopeError(f"{relative}:{number}: неверная ширина строки")
    return [{key: value or "" for key, value in row.items()} for row in rows if (row.get(id_field) or "").strip()]
