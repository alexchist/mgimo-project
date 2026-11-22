#!/usr/bin/env python3
"""Build a throwaway workspace with dedicated precedent cards for MCP checks.

The workspace is a temporary directory, never the real checkout: it gets a copy of
the synthetic ``examples/demo`` as ``projects/lesson-demo`` and a ``.portfolio``
written by the real ``tools/precedent.py`` CLI (remember + retire). Nothing here
touches the repository's own ``projects/`` or ``.portfolio/``.

    python3 adapters/mcp/demo_workspace.py /tmp/strategist-mcp-demo
"""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys

REPO = Path(__file__).resolve().parents[2]
PRECEDENT_CLI = REPO / "tools" / "precedent.py"
CASE = "projects/lesson-demo"

CARDS = [
    {"ref": "D-001", "topic": "обещание продукта",
     "note": "До теста коммуникации отделить доступные функции от запланированных: групповой Q&A оказался roadmap без даты, а не текущей возможностью.",
     "when": "Если сообщение клиенту опирается на функции из плана развития."},
    {"ref": "C-002", "topic": "падение удержания и состав каналов",
     "note": "Сводное падение W4 совпало со сдвигом доли promo; внутри каналов удержание не упало. Сначала разложить изменение на ставки внутри сегментов и состав.",
     "when": "Если общая метрика удержания падает после смены маркетинга или источников привлечения."},
    {"ref": "C-004", "topic": "неполные события аналитики",
     "note": "Рост пропавших событий завершения ограничил сравнение недель; сначала проверить полноту трекинга.",
     "when": "Если метрика строится на событиях приложения и недавно менялась версия."},
    {"ref": "C-001", "topic": "цифры брифа не воспроизводятся",
     "note": "Проценты брифа не совпали с расчётом по исходной таблице; до обсуждения причин согласовать определение метрики, знаменатель и период.",
     "when": "Если в задаче приведены готовые проценты без выгрузки и спецификации.",
     "retire": "Учебная карточка отозвана для проверки: показывать только как историю."},
]


def run_precedent(root: Path, *args: str) -> dict:
    result = subprocess.run([sys.executable, str(PRECEDENT_CLI), *args], cwd=root, text=True,
                            capture_output=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"precedent.py {' '.join(args[:1])} failed: {result.stderr.strip()}")
    return json.loads(result.stdout)


def build(target: Path) -> dict:
    target = Path(target)
    if target.exists() and any(target.iterdir()):
        raise SystemExit(f"каталог не пуст: {target}")
    (target / "projects").mkdir(parents=True, exist_ok=True)
    shutil.copytree(REPO / "examples" / "demo", target / CASE)
    remembered = []
    for card in CARDS:
        item = run_precedent(target, "remember", "lesson-demo", "--ref", card["ref"], "--topic", card["topic"],
                             "--note", card["note"], "--when", card["when"])
        if card.get("retire"):
            item = run_precedent(target, "retire", item["id"], "--reason", card["retire"])
        remembered.append({"id": item["id"], "ref": card["ref"], "retired": item["retired"]})
    return {"root": str(target), "case": CASE, "cards": remembered}


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: demo_workspace.py <empty-target-dir>")
    print(json.dumps(build(Path(sys.argv[1])), ensure_ascii=False, indent=2))
