#!/usr/bin/env python3
"""Deterministic utilities for the Product Factory Strategist folder.

The program extracts and checks evidence. It deliberately does not rank options,
write recommendations, or approve business decisions.
"""

from __future__ import annotations

import argparse
import base64
import csv
import datetime as dt
import hashlib
from html.parser import HTMLParser
import io
import ipaddress
import json
import math
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import zipfile

VERSION = "0.5.0"
ROOT = Path(__file__).resolve().parents[1]
ID_RE = re.compile(r"^[A-Z]+-\d{3,}$")
OP_STATUSES = {"planned", "in_progress", "succeeded", "failed", "outcome_unknown"}
COST_STATUSES = {"known", "included_subscription", "unknown", "not_applicable"}
CLAIM_TYPES = {"fact", "hypothesis", "forecast", "interpretation"}
CLAIM_STATUSES = {"active", "disputed", "retracted", "superseded"}
DECISION_STATUSES = {"pending", "recommended", "accepted", "rejected", "simulated", "superseded"}
DECISION_KINDS = {"human", "agent_recommendation", "simulated"}
COMMITMENT_STATUSES = {"proposed", "confirmed", "in_progress", "done", "cancelled", "overdue"}
ARTIFACT_STAGES = {"scaffold", "working", "decision_draft", "decision_recorded"}
REQUIRED_PROJECT_FILES = [
    "project.json", "source-policy.json", "brief.md", "state.md", "options.md", "strategy.md",
    "sources/index.json", "evidence/claims.csv", "evidence/conclusions.csv",
    "decisions/decisions.csv", "commitments.csv", "revisions/revision-log.csv", "runs/operations.csv",
    "runs/ingest-failures.csv",
]
REVISION_SNAPSHOT_DOCUMENTS = ("brief.md", "options.md", "strategy.md", "decision-memo.md", "state.md")
REVISION_SNAPSHOT_CONTRACT = "strategist.revision-snapshot/1.0"
SECRET_QUERY_KEYS = {"token", "sig", "signature", "key", "password", "secret", "auth", "authorization",
                     "access_token", "api_key", "apikey", "session", "sessionid", "code"}


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def atomic_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as tmp:
        tmp.write(content)
        tmp_path = Path(tmp.name)
    tmp_path.replace(path)


def atomic_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("wb", dir=path.parent, delete=False) as tmp:
        tmp.write(content)
        tmp_path = Path(tmp.name)
    tmp_path.replace(path)


def load_json(path: Path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def dump_json(path: Path, value) -> None:
    atomic_text(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def read_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def write_rows(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", newline="", dir=path.parent, delete=False) as tmp:
        writer = csv.DictWriter(tmp, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
        tmp_path = Path(tmp.name)
    tmp_path.replace(path)


def rows_text(fieldnames: list[str], rows: list[dict[str, str]]) -> str:
    handle = io.StringIO(newline="")
    writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore", lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return handle.getvalue()


def detect_csv_dialect(raw: str):
    try:
        return csv.Sniffer().sniff(raw[:8192], delimiters=",;\t")
    except csv.Error:
        return csv.excel


def validated_csv_headers(values: list[str]) -> list[str]:
    headers = [value.strip() for value in values]
    if not headers:
        raise ValueError("CSV: строка заголовков пуста.")
    empty = [str(index) for index, value in enumerate(headers, start=1) if not value]
    if empty:
        raise ValueError("CSV: пустые заголовки в колонках " + ", ".join(empty) + ".")
    duplicates = sorted({value for value in headers if headers.count(value) > 1})
    if duplicates:
        raise ValueError("CSV: повторяющиеся заголовки после trim: " + ", ".join(duplicates) + ".")
    return headers


def read_csv_dict(path: Path) -> tuple[list[dict[str, str | None]], list[str], str]:
    raw = path.read_text(encoding="utf-8-sig")
    dialect = detect_csv_dialect(raw)
    reader = csv.reader(io.StringIO(raw, newline=""), dialect)
    try:
        columns = validated_csv_headers(next(reader))
    except StopIteration:
        return [], [], getattr(dialect, "delimiter", ",")
    rows: list[dict[str, str | None]] = []
    previous_line = 1
    for record_number, values in enumerate(reader, start=2):
        end_line = reader.line_num
        start_line = previous_line + 1
        previous_line = end_line
        if len(values) > len(columns):
            raise ValueError(
                f"CSV record {record_number}, physical lines {start_line}-{end_line}: "
                f"лишние ячейки ({len(values)} вместо {len(columns)}); схема неоднозначна."
            )
        padded: list[str | None] = values + [None] * (len(columns) - len(values))
        rows.append(dict(zip(columns, padded)))
    return rows, columns, getattr(dialect, "delimiter", ",")


def next_id(existing: list[str], prefix: str) -> str:
    values = [int(item.split("-", 1)[1]) for item in existing if re.fullmatch(fr"{prefix}-\d+", item)]
    return f"{prefix}-{max(values, default=0) + 1:03d}"


def project_root(value: str) -> Path:
    root = Path(value).resolve()
    if not (root / "project.json").is_file():
        raise SystemExit(f"Не найден project.json: {root}. Сначала выполните init.")
    return root


def command_doctor(_args: argparse.Namespace) -> int:
    checks = {
        "python": sys.version.split()[0],
        "pdftotext": shutil.which("pdftotext"),
        "pdfinfo": shutil.which("pdfinfo"),
        "libreoffice_optional": shutil.which("libreoffice"),
        "network_required": False,
        "paid_api_required": False,
    }
    checks["pdf_text_extraction"] = bool(checks["pdftotext"])
    print(json.dumps(checks, ensure_ascii=False, indent=2))
    return 0 if checks["pdf_text_extraction"] else 2


def command_init(args: argparse.Namespace) -> int:
    target = Path(args.directory).resolve()
    if target.exists() and any(target.iterdir()) and not args.allow_existing:
        raise SystemExit("Каталог не пуст. Укажите --allow-existing, чтобы добавить только отсутствующие файлы.")
    target.mkdir(parents=True, exist_ok=True)
    template = ROOT / "templates" / "project"
    for source in template.rglob("*"):
        relative = source.relative_to(template)
        destination = target / relative
        if source.is_dir():
            destination.mkdir(parents=True, exist_ok=True)
        elif not destination.exists():
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
    metadata = load_json(target / "project.json", {})
    metadata.update({"slug": args.slug, "title": args.title or args.slug, "created_at": metadata.get("created_at") or now()})
    dump_json(target / "project.json", metadata)
    print(target)
    return 0


class VisibleHTML(HTMLParser):
    allowed = {"title", "h1", "h2", "h3", "h4", "p", "li", "th", "td", "caption", "blockquote",
               "div", "section", "article", "main", "aside", "header", "footer", "span", "dt", "dd", "pre", "code"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.skip = 0
        self.stack: list[tuple[str, int, list[str]]] = []
        self.counts: dict[str, int] = {}
        self.records: list[tuple[str, str]] = []

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag in {"script", "style", "noscript", "svg"}:
            self.skip += 1
        if not self.skip and tag in self.allowed:
            self.counts[tag] = self.counts.get(tag, 0) + 1
            self.stack.append((tag, self.counts[tag], []))

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in {"script", "style", "noscript", "svg"} and self.skip:
            self.skip -= 1
            return
        if not self.skip and self.stack and self.stack[-1][0] == tag:
            name, index, parts = self.stack.pop()
            text = " ".join("".join(parts).split())
            if text:
                self.records.append((f"{name}[{index}]", text))

    def handle_data(self, data):
        if not self.skip:
            for _tag, _index, parts in self.stack:
                parts.append(data)


def extract_html_bytes(data: bytes, encoding: str = "utf-8") -> tuple[list[tuple[str, str]], list[str]]:
    parser = VisibleHTML()
    parser.feed(data.decode(encoding, errors="replace"))
    gaps = ["Извлечён только статический HTML-текст: JavaScript-rendered content, CSS visibility, canvas, media and linked pages не интерпретированы."]
    if not parser.records:
        gaps.append("Видимый текст в поддерживаемых HTML-элементах не найден.")
    return parser.records, gaps


def extract_plain_bytes(data: bytes, encoding: str = "utf-8") -> tuple[list[tuple[str, str]], list[str]]:
    text = data.decode(encoding, errors="replace")
    records = [(f"line:{line_number}", line) for line_number, line in enumerate(text.splitlines(), start=1) if line]
    gaps = ["Текст прочитан построчно; разметка, ссылки и вложенные media не интерпретировались."]
    if not records:
        gaps.append("Текстовый ответ пуст.")
    return records, gaps


def extract_csv(path: Path) -> tuple[list[tuple[str, str]], list[str]]:
    raw = path.read_text(encoding="utf-8-sig")
    dialect = detect_csv_dialect(raw)
    reader = csv.reader(io.StringIO(raw, newline=""), dialect)
    try:
        first = next(reader)
    except StopIteration:
        return [], ["CSV пуст."]
    headers = validated_csv_headers(first)
    records: list[tuple[str, str]] = []
    gaps: list[str] = []
    previous_line = 1
    for record_number, row in enumerate(reader, start=2):
        end_line = reader.line_num
        start_line = previous_line + 1
        previous_line = end_line
        if len(row) != len(headers):
            relation = "лишние ячейки" if len(row) > len(headers) else "недостающие ячейки"
            gaps.append(
                f"CSV record {record_number}, physical lines {start_line}-{end_line}: {relation} "
                f"({len(row)} вместо {len(headers)})."
            )
        for column_number, value in enumerate(row, start=1):
            header = headers[column_number - 1] if column_number <= len(headers) else f"extra_{column_number}"
            if value != "":
                line_part = f",lines:{start_line}-{end_line}" if start_line != end_line else ""
                records.append((f"row:{record_number}{line_part},column:{header}", value))
    return records, gaps


def _docx_text(element: ET.Element) -> str:
    return "".join(node.text or "" for node in element.iter() if node.tag.endswith("}t"))


def extract_docx(path: Path) -> tuple[list[tuple[str, str]], list[str]]:
    records: list[tuple[str, str]] = []
    gaps: list[str] = []
    try:
        with zipfile.ZipFile(path) as archive:
            root = ET.fromstring(archive.read("word/document.xml"))
    except (zipfile.BadZipFile, KeyError, ET.ParseError) as exc:
        raise ValueError(f"DOCX повреждён или не поддерживается: {exc}") from exc
    paragraph = 0
    table_number = 0
    for child in list(next(node for node in root.iter() if node.tag.endswith("}body"))):
        if child.tag.endswith("}p"):
            paragraph += 1
            text = _docx_text(child).strip()
            if text:
                records.append((f"paragraph:{paragraph}", text))
        elif child.tag.endswith("}tbl"):
            table_number += 1
            for row_number, row in enumerate([n for n in child if n.tag.endswith("}tr")], start=1):
                cells = [n for n in row if n.tag.endswith("}tc")]
                for column_number, cell in enumerate(cells, start=1):
                    text = _docx_text(cell).strip()
                    if text:
                        records.append((f"table:{table_number}!R{row_number}C{column_number}", text))
    if not records:
        gaps.append("В основном XML DOCX нет извлекаемого текста; колонтитулы, комментарии и изображения не извлечены.")
    gaps.append("Не извлечены текст из изображений, рукописные пометки, комментарии и отслеживаемые правки вне основного текста.")
    return records, gaps


def _xlsx_shared(archive: zipfile.ZipFile) -> list[str]:
    try:
        root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
    except KeyError:
        return []
    return ["".join(node.text or "" for node in item.iter() if node.tag.endswith("}t")) for item in root]


def extract_xlsx(path: Path) -> tuple[list[tuple[str, str]], list[str]]:
    records: list[tuple[str, str]] = []
    gaps = [
        "Формулы не вычисляются: фиксируются формула и сохранённое cached value, если оно присутствует.",
        "Стили, форматы дат, валюты, проценты и единицы XLSX не интерпретируются; числовые serial values остаются исходными.",
    ]
    style_ids: set[str] = set()
    try:
        archive = zipfile.ZipFile(path)
        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        rels = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    except (zipfile.BadZipFile, KeyError, ET.ParseError) as exc:
        raise ValueError(f"XLSX повреждён или не поддерживается: {exc}") from exc
    with archive:
        relationships = {node.attrib["Id"]: node.attrib["Target"] for node in rels}
        shared = _xlsx_shared(archive)
        for sheet in [node for node in workbook.iter() if node.tag.endswith("}sheet")]:
            name = sheet.attrib.get("name", "unknown")
            rel_id = next((value for key, value in sheet.attrib.items() if key.endswith("}id")), None)
            target = relationships.get(rel_id or "", "")
            member = target.lstrip("/") if target.startswith("/xl/") else "xl/" + target.lstrip("/")
            try:
                root = ET.fromstring(archive.read(member))
            except (KeyError, ET.ParseError):
                gaps.append(f"Лист {name}: XML {member} не прочитан.")
                continue
            for cell in [node for node in root.iter() if node.tag.endswith("}c")]:
                address = cell.attrib.get("r", "?")
                cell_type = cell.attrib.get("t", "")
                style_id = cell.attrib.get("s", "")
                if style_id:
                    style_ids.add(style_id)
                formula = next((n.text or "" for n in cell if n.tag.endswith("}f")), "")
                value = next((n.text or "" for n in cell if n.tag.endswith("}v")), "")
                inline = "".join(n.text or "" for n in cell.iter() if n.tag.endswith("}t"))
                if cell_type == "s" and value:
                    try:
                        value = shared[int(value)]
                    except (ValueError, IndexError):
                        gaps.append(f"{name}!{address}: неверный индекс shared string {value!r}.")
                elif cell_type == "inlineStr":
                    value = inline
                if formula:
                    rendered = f"formula={formula}; cached={value if value else '[missing]'}"
                    if not value:
                        gaps.append(f"{name}!{address}: у формулы нет cached value.")
                else:
                    rendered = value
                if style_id and rendered != "":
                    rendered = f"style_id={style_id}; value={rendered}"
                if rendered != "":
                    records.append((f"{name}!{address}", rendered))
    if style_ids:
        gaps.append(f"Обнаружены, но не интерпретированы style_id: {', '.join(sorted(style_ids))}.")
    return records, gaps


def extract_pdf(path: Path) -> tuple[list[tuple[str, str]], list[str]]:
    executable = shutil.which("pdftotext")
    if not executable:
        raise ValueError("pdftotext не найден; OCR автоматически не запускается.")
    process = subprocess.run([executable, "-layout", str(path), "-"], capture_output=True, check=False)
    if process.returncode:
        raise ValueError(process.stderr.decode("utf-8", errors="replace").strip() or "pdftotext завершился с ошибкой")
    text = process.stdout.decode("utf-8", errors="replace")
    records: list[tuple[str, str]] = []
    gaps: list[str] = []
    pages = text.split("\f")
    if pages and not pages[-1].strip():
        pages.pop()
    for page_number, page in enumerate(pages, start=1):
        lines = [(line_number, " ".join(line.split())) for line_number, line in enumerate(page.splitlines(), start=1) if line.strip()]
        if not lines:
            gaps.append(f"Страница {page_number}: текстовый слой пуст; OCR не выполнялся.")
        for line_number, line in lines:
            records.append((f"page:{page_number},line:{line_number}", line))
    if not pages:
        gaps.append("PDF не содержит извлечённых страниц.")
    return records, gaps


def allowed_hosts(root: Path) -> set[str]:
    policy = load_json(root / "source-policy.json", {"allowed_hosts": []})
    return {str(item).lower().rstrip(".") for item in policy.get("allowed_hosts", [])}


def validate_public_url(url: str, hosts: set[str]) -> None:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Разрешены только HTTPS URL с именем хоста.")
    host = parsed.hostname.lower().rstrip(".")
    if host not in hosts:
        raise ValueError(f"Хост {host} отсутствует в source-policy.json.")
    for _family, _type, _proto, _canon, sockaddr in socket.getaddrinfo(host, 443):
        address = ipaddress.ip_address(sockaddr[0])
        if not address.is_global:
            raise ValueError(f"Хост {host} разрешается в непубличный адрес; загрузка отклонена.")


class SafeRedirect(urllib.request.HTTPRedirectHandler):
    def __init__(self, hosts: set[str]):
        self.hosts = hosts
        super().__init__()

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        validate_public_url(newurl, self.hosts)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch_url(url: str, root: Path) -> tuple[bytes, str, str, str]:
    hosts = allowed_hosts(root)
    validate_public_url(url, hosts)
    opener = urllib.request.build_opener(SafeRedirect(hosts))
    request = urllib.request.Request(url, headers={"User-Agent": f"strategist-folder/{VERSION}"})
    with opener.open(request, timeout=20) as response:
        final = response.geturl()
        validate_public_url(final, hosts)
        content_type = response.headers.get_content_type()
        if content_type not in {"text/html", "text/plain"}:
            raise ValueError(f"Неподдерживаемый Content-Type: {content_type}")
        data = response.read(5_000_001)
        if len(data) > 5_000_000:
            raise ValueError("Страница больше лимита 5 MB.")
        charset = response.headers.get_content_charset() or "utf-8"
    return data, final, charset, content_type


def sanitized_url(url: str) -> tuple[str, list[str]]:
    parsed = urllib.parse.urlparse(url)
    host = parsed.hostname or ""
    if parsed.port:
        host = f"{host}:{parsed.port}"
    kept: list[tuple[str, str]] = []
    redacted: list[str] = []
    for key, value in urllib.parse.parse_qsl(parsed.query, keep_blank_values=True):
        normalized = key.lower()
        if normalized in SECRET_QUERY_KEYS or normalized.startswith("x-amz-") or normalized.startswith("goog-"):
            redacted.append(key)
        else:
            kept.append((key, value))
    query = urllib.parse.urlencode(kept, doseq=True)
    return urllib.parse.urlunparse((parsed.scheme, host, parsed.path, parsed.params, query, "")), redacted


def render_extract(source_id: str, records: list[tuple[str, str]], gaps: list[str]) -> str:
    lines = [f"# Извлечение {source_id}", "", "Автоматическое извлечение; это не интерпретация и не подтверждение истинности.", "", "## Фрагменты", ""]
    for locator, text in records:
        lines.append(f"- `{locator}` — {text.replace(chr(10), ' ')}")
    lines.extend(["", "## Пробелы и ограничения", ""])
    lines.extend(f"- {gap}" for gap in gaps)
    if not gaps:
        lines.append("- Автоматически обнаруженных пробелов нет; смысловая полнота требует проверки человеком/агентом.")
    return "\n".join(lines) + "\n"


def log_ingest_failure(root: Path, source_id: str, input_value: str, error: str) -> None:
    path = root / "runs" / "ingest-failures.csv"
    fields = ["failure_id", "recorded_at", "source_id", "input", "status", "cost_status", "error"]
    rows = read_rows(path)
    rows.append({"failure_id": next_id([row.get("failure_id", "") for row in rows], "IF"), "recorded_at": now(),
                 "source_id": source_id, "input": input_value, "status": "failed", "cost_status": "unknown", "error": error})
    write_rows(path, fields, rows)


def all_source_ids(root: Path, index: list[dict]) -> list[str]:
    identifiers = [item.get("source_id", "") for item in index]
    for directory in [root / "sources" / "originals", root / "sources" / "extracts", root / "sources" / ".staging"]:
        if directory.exists():
            for path in directory.iterdir():
                match = re.match(r"(S-\d+)", path.name)
                if match:
                    identifiers.append(match.group(1))
    return identifiers


def command_ingest(args: argparse.Namespace) -> int:
    root = project_root(args.project)
    index_path = root / "sources" / "index.json"
    if not index_path.is_file():
        raise ValueError("Отсутствует sources/index.json; восстановите scaffold до ingest.")
    index = load_json(index_path, [])
    source_id = next_id(all_source_ids(root, index), "S")
    retrieved = now()
    original_dir = root / "sources" / "originals"
    extract_dir = root / "sources" / "extracts"
    staging_dir = root / "sources" / ".staging"
    original_dir.mkdir(parents=True, exist_ok=True)
    extract_dir.mkdir(parents=True, exist_ok=True)
    staging_dir.mkdir(parents=True, exist_ok=True)
    stage_source = staging_dir / f"{source_id}.source"
    stage_extract = staging_dir / f"{source_id}.extract.md"
    pending = staging_dir / f"{source_id}.pending.json"
    safe_input = args.input
    try:
        is_network = "://" in args.input
        redacted: list[str] = []
        if is_network:
            safe_input, _input_redacted = sanitized_url(args.input)
            data, final_url, charset, content_type = fetch_url(args.input, root)
            filename = re.sub(r"[^a-zA-Z0-9._-]+", "_", Path(urllib.parse.urlparse(final_url).path).name or ("response.txt" if content_type == "text/plain" else "index.html"))
            stage_source.write_bytes(data)
            records, gaps = extract_plain_bytes(data, charset) if content_type == "text/plain" else extract_html_bytes(data, charset)
            kind = "web-text" if content_type == "text/plain" else "web"
            origin, redacted = sanitized_url(final_url)
            if redacted:
                gaps.append("Из origin удалены секретоподобные query parameters: " + ", ".join(sorted(redacted)) + "; сохранённый URL не является точным fetch URL.")
        else:
            source = Path(args.input).resolve()
            if not source.is_file():
                raise ValueError(f"Файл не найден: {source}")
            suffix = source.suffix.lower()
            extractors = {".pdf": extract_pdf, ".docx": extract_docx, ".csv": extract_csv, ".xlsx": extract_xlsx,
                          ".html": lambda p: extract_html_bytes(p.read_bytes()), ".htm": lambda p: extract_html_bytes(p.read_bytes()),
                          ".txt": lambda p: extract_plain_bytes(p.read_bytes()),
                          ".md": lambda p: extract_plain_bytes(p.read_bytes()),
                          ".markdown": lambda p: extract_plain_bytes(p.read_bytes())}
            if suffix not in extractors:
                raise ValueError(f"Формат {suffix or '[без расширения]'} не поддерживается.")
            filename = source.name
            shutil.copy2(source, stage_source)
            records, gaps = extractors[suffix](stage_source)
            kind = suffix.lstrip(".")
            origin = args.input
        stored = original_dir / f"{source_id}__{filename}"
        extract_path = extract_dir / f"{source_id}.md"
        if stored.exists() or extract_path.exists():
            raise ValueError(f"Целевые артефакты {source_id} уже существуют; повтор не выполнен.")
        atomic_text(stage_extract, render_extract(source_id, records, gaps))
        entry = {
            "source_id": source_id, "kind": kind, "title": args.title or filename, "origin": origin,
            "stored_path": stored.relative_to(root).as_posix(), "extract_path": extract_path.relative_to(root).as_posix(),
            "sha256": sha256(stage_source), "extract_sha256": sha256(stage_extract), "retrieved_at": retrieved,
            "permission": args.permission, "synthetic": bool(args.synthetic), "record_count": len(records),
            "gaps": gaps, "status": "active",
        }
        manifest = {"source_id": source_id, "created_at": now(), "entry": entry,
                    "stage_source": stage_source.relative_to(root).as_posix(), "stage_extract": stage_extract.relative_to(root).as_posix(),
                    "final_source": stored.relative_to(root).as_posix(), "final_extract": extract_path.relative_to(root).as_posix()}
        dump_json(pending, manifest)
        stage_source.replace(stored)
        stage_extract.replace(extract_path)
        index.append(entry)
        dump_json(index_path, index)
        pending.unlink()
        print(json.dumps(entry, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        log_ingest_failure(root, source_id, safe_input, str(exc))
        if not pending.exists():
            for path in [stage_source, stage_extract]:
                if path.exists():
                    path.unlink()
        raise


def command_ingest_recover(args: argparse.Namespace) -> int:
    root = project_root(args.project)
    pending = root / "sources" / ".staging" / f"{args.source_id}.pending.json"
    if not pending.is_file():
        raise SystemExit(f"Pending ingest {args.source_id} не найден.")
    manifest = load_json(pending, {})
    if manifest.get("source_id") != args.source_id:
        raise SystemExit("Pending manifest имеет другой source_id.")
    index_path = root / "sources" / "index.json"
    index = load_json(index_path, [])
    if not isinstance(index, list) or any(not isinstance(item, dict) for item in index):
        raise SystemExit("sources/index.json должен быть массивом объектов; recovery не начат.")
    indexed = any(item.get("source_id") == args.source_id for item in index)
    entry = manifest.get("entry")
    if not isinstance(entry, dict) or not entry.get("sha256") or not entry.get("extract_sha256"):
        raise SystemExit("Pending manifest не содержит ожидаемые hashes; recovery не начат.")
    try:
        paths = {name: (root / manifest[name]).resolve() for name in ["stage_source", "stage_extract", "final_source", "final_extract"]}
    except (KeyError, TypeError):
        raise SystemExit("Pending manifest не содержит полный набор путей; recovery не начат.") from None
    if any(not path.is_relative_to(root) for path in paths.values()):
        raise SystemExit("Pending manifest выводит путь за пределы проекта.")
    if len(set(paths.values())) != len(paths):
        raise SystemExit("Pending manifest повторно использует один путь; recovery не начат.")
    expected_hash = {
        "stage_source": entry["sha256"], "final_source": entry["sha256"],
        "stage_extract": entry["extract_sha256"], "final_extract": entry["extract_sha256"],
    }
    for name, path in paths.items():
        if path.exists() and not path.is_file():
            raise SystemExit(f"{name} существует, но не является файлом; recovery не начат.")
        if path.is_file() and sha256(path) != expected_hash[name]:
            raise SystemExit(f"{name} изменён после pending manifest; recovery не начат.")
    if args.mode == "complete":
        if indexed:
            indexed_rows = [item for item in index if item.get("source_id") == args.source_id]
            if len(indexed_rows) != 1 or indexed_rows[0] != entry:
                raise SystemExit("Индексированная запись отличается от pending manifest; recovery не начат.")
            if not paths["final_source"].is_file() or not paths["final_extract"].is_file():
                raise SystemExit("Источник индексирован, но final artifacts отсутствуют; recovery не начат.")
            for name in ["stage_source", "stage_extract"]:
                if paths[name].is_file():
                    paths[name].unlink()
            pending.unlink()
            print(json.dumps({"source_id": args.source_id, "result": "already-indexed; pending removed"}, ensure_ascii=False))
            return 0
        for stage_name, final_name in [("stage_source", "final_source"), ("stage_extract", "final_extract")]:
            if not paths[stage_name].is_file() and not paths[final_name].is_file():
                raise SystemExit(f"Нет ни staged, ни final артефакта {final_name}; recovery не начат.")
        for stage_name, final_name in [("stage_source", "final_source"), ("stage_extract", "final_extract")]:
            if not paths[final_name].is_file():
                paths[stage_name].replace(paths[final_name])
            elif paths[stage_name].is_file():
                paths[stage_name].unlink()
        if sha256(paths["final_source"]) != entry["sha256"] or sha256(paths["final_extract"]) != entry["extract_sha256"]:
            raise SystemExit("Hash recovery artifacts не совпадает с pending manifest.")
        index.append(entry)
        dump_json(index_path, index)
        pending.unlink()
        result = "completed"
    else:
        if indexed:
            raise SystemExit("Источник уже индексирован; discard запрещён.")
        for path in paths.values():
            if path.is_file():
                path.unlink()
        pending.unlink()
        result = "discarded"
    print(json.dumps({"source_id": args.source_id, "result": result}, ensure_ascii=False))
    return 0


def parse_number(value: str | None) -> float | None:
    normalized = (value or "").strip().replace(" ", "").replace(",", ".")
    if not normalized:
        return None
    try:
        result = float(normalized)
    except ValueError:
        return None
    return result if math.isfinite(result) else None


def command_profile(args: argparse.Namespace) -> int:
    source = Path(args.csv).resolve()
    rows, columns, delimiter = read_csv_dict(source)
    result = {"file": str(source), "sha256": sha256(source), "delimiter": delimiter, "rows": len(rows), "columns": {}}
    for column in columns:
        values = [(row.get(column) or "") for row in rows]
        numbers = [number for value in values if (number := parse_number(value)) is not None]
        item = {"missing": sum(value == "" for value in values), "distinct_nonempty": len(set(value for value in values if value != "")), "numeric_count": len(numbers)}
        if numbers:
            item.update({"min": min(numbers), "max": max(numbers), "mean": sum(numbers) / len(numbers)})
        result["columns"][column] = item
    output = Path(args.output)
    dump_json(output, result)
    print(output)
    return 0


def command_retention(args: argparse.Namespace) -> int:
    source = Path(args.csv).resolve()
    rows, columns, delimiter = read_csv_dict(source)
    required = [args.cohort, args.period, args.active, args.size]
    missing = [name for name in required if name not in columns]
    if missing:
        raise SystemExit("Нет колонок: " + ", ".join(missing))
    if not rows:
        raise SystemExit("CSV содержит заголовок, но не содержит строк данных для retention.")
    output_rows = []
    grouped: dict[tuple[str, str], list[float]] = {}
    for line, row in enumerate(rows, start=2):
        active = parse_number(row[args.active])
        size = parse_number(row[args.size])
        if active is None or size is None or size <= 0 or active < 0 or active > size:
            raise SystemExit(f"Строка {line}: нужны 0 <= active <= size и size > 0.")
        rate = active / size
        if row.get(args.cohort) is None or row.get(args.period) is None:
            raise SystemExit(f"Строка {line}: cohort/period отсутствуют.")
        key = (str(row[args.cohort]), str(row[args.period]))
        totals = grouped.setdefault(key, [0.0, 0.0])
        totals[0] += active
        totals[1] += size
        output_rows.append({
            "cohort": str(row[args.cohort]), "period": str(row[args.period]), "active_users": f"{active:g}",
            "cohort_size": f"{size:g}", "retention_rate": f"{rate:.6f}", "source_locator": f"row:{line}",
        })
    output = Path(args.output)
    write_rows(output, ["cohort", "period", "active_users", "cohort_size", "retention_rate", "source_locator"], output_rows)
    summary = output.with_suffix(output.suffix + ".cohort-summary.csv")
    summary_rows = [{"cohort": cohort, "period": period, "active_users": f"{values[0]:g}", "cohort_size": f"{values[1]:g}",
                     "retention_rate": f"{values[0] / values[1]:.6f}", "aggregation": "sum(active_users)/sum(cohort_size)"}
                    for (cohort, period), values in sorted(grouped.items())]
    write_rows(summary, ["cohort", "period", "active_users", "cohort_size", "retention_rate", "aggregation"], summary_rows)
    method = output.with_suffix(output.suffix + ".method.md")
    atomic_text(method, f"# Метод расчёта\n\nВход: `{source}` (sha256 `{sha256(source)}`), delimiter `{delimiter}`.\n\nДетально: `retention_rate = {args.active} / {args.size}` для каждой строки. Сводка по cohort+period: `sum({args.active}) / sum({args.size})`, то есть взвешенная доля, а не среднее процентов. Единица результата — доля, не процент. Скрипт не делает причинных или стратегических выводов.\n")
    print(output)
    return 0


def command_operation(args: argparse.Namespace) -> int:
    root = project_root(args.project)
    path = root / "runs" / "operations.csv"
    fields = ["operation_id", "started_at", "finished_at", "status", "tool", "inputs", "artifact", "cost_status", "cost_amount", "currency", "human_minutes", "related_operation_id", "resolution", "notes"]
    rows = read_rows(path)
    if args.action == "start":
        operation_id = args.id or next_id([row["operation_id"] for row in rows], "OP")
        if any(row["operation_id"] == operation_id for row in rows):
            raise SystemExit(f"Операция {operation_id} уже существует; история не перезаписана.")
        rows.append({"operation_id": operation_id, "started_at": now(), "finished_at": "", "status": "in_progress", "tool": args.tool, "inputs": args.inputs, "artifact": "", "cost_status": "unknown", "cost_amount": "", "currency": "", "human_minutes": "", "related_operation_id": "", "resolution": "", "notes": args.notes})
    elif args.action == "resolve":
        if not args.resolution:
            raise SystemExit("operation resolve требует --resolution.")
        matches = [row for row in rows if row.get("operation_id") == args.id]
        if len(matches) != 1 or matches[0].get("status") != "outcome_unknown":
            raise SystemExit(f"Разрешить можно одну outcome_unknown операцию; для {args.id} условие не выполнено.")
        operation_id = next_id([row.get("operation_id", "") for row in rows], "OP")
        if args.cost_status == "known" and (not args.cost_amount or not args.currency):
            raise SystemExit("Для cost-status=known нужны --cost-amount и --currency.")
        rows.append({"operation_id": operation_id, "started_at": now(), "finished_at": now(), "status": "succeeded",
                     "tool": args.tool or "verification", "inputs": args.inputs, "artifact": args.artifact,
                     "cost_status": args.cost_status, "cost_amount": args.cost_amount, "currency": args.currency,
                     "human_minutes": args.human_minutes, "related_operation_id": args.id,
                     "resolution": args.resolution, "notes": args.notes})
    else:
        operation_id = args.id
        matches = [row for row in rows if row["operation_id"] == operation_id]
        if len(matches) != 1:
            raise SystemExit(f"Операция {operation_id}: найдено записей {len(matches)}.")
        row = matches[0]
        if row["status"] != "in_progress":
            raise SystemExit(f"Операция {operation_id} уже имеет статус {row['status']}; история не перезаписана.")
        status = {"finish": "succeeded", "fail": "failed", "unknown": "outcome_unknown"}[args.action]
        if args.cost_status == "known" and (not args.cost_amount or not args.currency):
            raise SystemExit("Для cost-status=known нужны --cost-amount и --currency.")
        row.update({"finished_at": now(), "status": status, "artifact": args.artifact, "cost_status": args.cost_status,
                    "cost_amount": args.cost_amount, "currency": args.currency, "human_minutes": args.human_minutes,
                    "notes": "; ".join(filter(None, [row.get("notes", ""), args.notes]))})
    write_rows(path, fields, rows)
    print(operation_id)
    return 0


def command_recover(args: argparse.Namespace) -> int:
    root = project_root(args.project)
    path = root / "runs" / "operations.csv"
    rows = read_rows(path)
    changed = []
    for row in rows:
        if row["status"] == "in_progress":
            row["status"] = "outcome_unknown"
            row["finished_at"] = now()
            row["cost_status"] = "unknown"
            row["notes"] = "; ".join(filter(None, [row.get("notes", ""), "Помечено recover после прерывания; перед повтором проверить артефакт/внешний результат."]))
            changed.append(row["operation_id"])
    if rows:
        write_rows(path, list(rows[0].keys()), rows)
    print(json.dumps({"marked_outcome_unknown": changed}, ensure_ascii=False))
    return 0


def command_revise(args: argparse.Namespace) -> int:
    root = project_root(args.project)
    claims_path = root / "evidence" / "claims.csv"
    fields = ["claim_id", "type", "statement", "source_ids", "locator", "period", "unit", "status", "supersedes", "limitations"]
    claims = read_rows(claims_path)
    match = [row for row in claims if row["claim_id"] == args.claim]
    if len(match) != 1:
        raise SystemExit(f"Утверждение {args.claim}: найдено записей {len(match)}.")
    old = match[0]
    if old["status"] != "active" and not args.allow_nonactive:
        raise SystemExit(f"Утверждение {args.claim} уже имеет статус {old['status']}.")
    old_status = old["status"]
    old["status"] = args.status
    new_id = ""
    evidence_action = "not_applicable"
    if args.new_statement:
        new_id = next_id([row["claim_id"] for row in claims], "E")
        new_type = args.type or old["type"]
        if bool(args.source_ids) != bool(args.locator):
            raise SystemExit("Для нового evidence укажите вместе --source-ids и --locator.")
        if args.reuse_evidence:
            if args.source_ids or args.locator:
                raise SystemExit("--reuse-evidence нельзя сочетать с новыми --source-ids/--locator.")
            if not args.reuse_reason:
                raise SystemExit("--reuse-evidence требует --reuse-reason.")
            new_sources, new_locator = old.get("source_ids", ""), old.get("locator", "")
            evidence_action = "reused: " + args.reuse_reason
        else:
            new_sources, new_locator = args.source_ids or "", args.locator or ""
            evidence_action = "new" if new_sources else "none"
        if new_type == "fact" and (not new_sources or not new_locator):
            raise SystemExit("Новому активному факту нужны явные новые citations либо --reuse-evidence с причиной.")
        limitations = args.limitations
        if args.reuse_evidence:
            limitations = "; ".join(filter(None, [limitations, f"Evidence reused: {args.reuse_reason}"]))
        claims.append({"claim_id": new_id, "type": new_type, "statement": args.new_statement,
                       "source_ids": new_sources, "locator": new_locator,
                       "period": args.period or old["period"], "unit": args.unit or old["unit"], "status": "active",
                       "supersedes": old["claim_id"], "limitations": limitations})
        old["status"] = "superseded"
    conclusions_path = root / "evidence" / "conclusions.csv"
    conclusions = read_rows(conclusions_path)
    affected = []
    for row in conclusions:
        refs = {value.strip() for value in row.get("evidence_ids", "").split(";") if value.strip()}
        if args.claim in refs:
            row["review_needed"] = "yes"
            affected.append(row["conclusion_id"])
    conclusion_fields = ["conclusion_id", "statement", "evidence_ids", "alternative_explanations", "change_condition", "status", "review_needed"]
    decisions = read_rows(root / "decisions" / "decisions.csv")
    affected_decisions = []
    for row in decisions:
        refs = {value.strip() for value in row.get("conclusion_ids", "").split(";") if value.strip()}
        if refs.intersection(affected):
            affected_decisions.append(row["decision_id"])
    commitments = read_rows(root / "commitments.csv")
    affected_commitments = [row.get("commitment_id", "") for row in commitments if row.get("decision_id") in affected_decisions and row.get("commitment_id")]
    revision_path = root / "revisions" / "revision-log.csv"
    revision_fields = ["revision_id", "recorded_at", "old_claim_id", "old_status", "new_status", "new_claim_id", "reason", "evidence_action", "affected_conclusions", "affected_decisions", "affected_commitments", "human_review_required", "snapshot_manifest_sha256"]
    revisions = read_rows(revision_path)
    revision_id = next_id([row["revision_id"] for row in revisions], "R")
    snapshot = root / "revisions" / f"{revision_id}-before"
    snapshot_manifest = root / "revisions" / f"{revision_id}-before.manifest.json"
    if (root / "revisions").is_symlink() or snapshot.is_symlink():
        raise SystemExit("Архивы должны находиться в обычном каталоге revisions внутри кейса.")
    if snapshot.exists() and (not snapshot.is_dir() or any(p.name in REVISION_SNAPSHOT_DOCUMENTS for p in snapshot.iterdir())):
        raise SystemExit(f"Снимок {snapshot.name} уже существует; перезапись истории запрещена.")
    if snapshot_manifest.exists() or snapshot_manifest.is_symlink():
        raise SystemExit(f"Опись {snapshot_manifest.name} уже существует; перезапись истории запрещена.")
    snapshots: dict[str, bytes] = {}
    snapshot_inventory: dict[str, dict[str, str | int]] = {}
    for name in REVISION_SNAPSHOT_DOCUMENTS:
        source = root / name
        if source.is_file():
            content = source.read_bytes()
            snapshots[(snapshot / name).relative_to(root).as_posix()] = content
            snapshot_inventory[name] = {"sha256": sha256_bytes(content), "bytes": len(content)}
    snapshot_manifest_bytes = (json.dumps({
        "contract": REVISION_SNAPSHOT_CONTRACT,
        "revision_id": revision_id,
        "kind": "before_revision_archive",
        "files": snapshot_inventory,
    }, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    snapshot_manifest_digest = sha256_bytes(snapshot_manifest_bytes)
    revisions.append({"revision_id": revision_id, "recorded_at": now(), "old_claim_id": args.claim, "old_status": old_status,
                      "new_status": old["status"], "new_claim_id": new_id, "reason": args.reason,
                      "evidence_action": evidence_action,
                      "affected_conclusions": ";".join(affected), "affected_decisions": ";".join(affected_decisions),
                      "affected_commitments": ";".join(affected_commitments),
                      "human_review_required": "yes" if affected else "no",
                      "snapshot_manifest_sha256": snapshot_manifest_digest})
    report = root / "revisions" / f"{revision_id}.md"
    report_text = f"# {revision_id}: пересмотр основания\n\n- Старое утверждение: `{args.claim}` ({old_status} → {old['status']})\n- Новое утверждение: `{new_id or 'нет'}`\n- Evidence: {evidence_action}\n- Причина: {args.reason}\n- Выводы на проверку: {', '.join(affected) or 'нет автоматических связей'}\n- Исторические решения, которые могут быть затронуты: {', '.join(affected_decisions) or 'нет'}\n- Связанные обязательства на проверку: {', '.join(affected_commitments) or 'нет'}\n\n## Обязательный смысловой пересчёт агентом\n\nПосле проверки `C-*` заново сравнить рекомендацию с ближайшей альтернативой и обновить `options.md`, продуктовую и коммуникационную части `strategy.md`, матрицу обещаний, существующий `decision-memo.md` (в legacy 1.0 без него — краткое резюме в `state.md`) и cold-resume блок `state.md`. Явно перечислить изменившееся и неизменное.\n\nКод не менял и не отменял решения человека или обязательства. Пересчитанная рекомендация не является решением. Для затронутого действующего решения требуется новый явный человеческий выбор и новая append-only запись.\n"
    changes = {
        claims_path.relative_to(root).as_posix(): rows_text(fields, claims),
        conclusions_path.relative_to(root).as_posix(): rows_text(conclusion_fields, conclusions),
        revision_path.relative_to(root).as_posix(): rows_text(revision_fields, revisions),
        report.relative_to(root).as_posix(): report_text,
    }
    changes[report.relative_to(root).as_posix()] += f"\nСнимок существовавших документов до пересмотра: `{snapshot.name}/`; контрольная опись: `{snapshot_manifest.name}`. Сначала revise, затем редактура документов; снимок не восстанавливает правки, сделанные до вызова.\n"
    changes = {
        **snapshots,
        snapshot_manifest.relative_to(root).as_posix(): snapshot_manifest_bytes,
        **{name: text.encode("utf-8") for name, text in changes.items()},
    }
    pending = root / "revisions" / f".pending-{revision_id}.json"
    if pending.exists():
        raise SystemExit(f"Незавершённый {revision_id}: сначала revision-recover.")
    manifest = {"revision_id": revision_id, "created_at": now(), "encoding": "base64-bytes", "files": {}}
    for relative, after in changes.items():
        path = root / relative
        before_bytes = path.read_bytes() if path.exists() else b""
        after_bytes = after
        manifest["files"][relative] = {
            "existed": path.exists(),
            "before_b64": base64.b64encode(before_bytes).decode("ascii"),
            "after_b64": base64.b64encode(after_bytes).decode("ascii"),
        }
    dump_json(pending, manifest)
    for relative, after in changes.items():
        atomic_bytes(root / relative, after)
    pending.unlink()
    print(json.dumps({"revision_id": revision_id, "affected_conclusions": affected, "affected_decisions": affected_decisions, "affected_commitments": affected_commitments}, ensure_ascii=False))
    return 0


def command_revision_recover(args: argparse.Namespace) -> int:
    root = project_root(args.project)
    pending = root / "revisions" / f".pending-{args.revision}.json"
    if not pending.is_file():
        raise SystemExit(f"Pending revision {args.revision} не найден.")
    manifest = load_json(pending, {})
    if manifest.get("revision_id") != args.revision:
        raise SystemExit("Pending revision manifest имеет другой ID.")
    files = manifest.get("files", {})
    if not isinstance(files, dict) or not files:
        raise SystemExit("Pending revision не содержит файлов; recovery не начат.")
    prepared: list[tuple[Path, bool, bytes, bytes]] = []
    prepared_paths: set[Path] = set()
    for relative, versions in files.items():
        if not isinstance(relative, str):
            raise SystemExit("Pending revision содержит нестроковый путь; recovery не начат.")
        path = (root / relative).resolve()
        if not path.is_relative_to(root):
            raise SystemExit("Pending revision выводит путь за пределы проекта.")
        if path in prepared_paths:
            raise SystemExit("Pending revision повторно использует один путь; recovery не начат.")
        prepared_paths.add(path)
        if not isinstance(versions, dict):
            raise SystemExit(f"Pending revision: неверная запись {relative}; recovery не начат.")
        try:
            if "before_b64" in versions:
                before = base64.b64decode(versions["before_b64"], validate=True)
                after = base64.b64decode(versions["after_b64"], validate=True)
            else:
                before = versions.get("before", "").encode("utf-8")
                after = versions["after"].encode("utf-8")
        except (AttributeError, KeyError, TypeError, ValueError):
            raise SystemExit(f"Pending revision: версии {relative} повреждены; recovery не начат.") from None
        if path.exists() and not path.is_file():
            raise SystemExit(f"{relative} существует, но не является файлом; recovery не начат.")
        current = path.read_bytes() if path.is_file() else None
        existed = bool(versions.get("existed"))
        allowed = current in {before, after} if existed else current is None or current == after
        if not allowed:
            raise SystemExit(f"{relative} изменён после pending revision; recovery не начат.")
        prepared.append((path, existed, before, after))
    for path, existed, before, after in prepared:
        if args.mode == "complete":
            atomic_bytes(path, after)
        elif existed:
            atomic_bytes(path, before)
        elif path.exists():
            path.unlink()
    pending.unlink()
    print(json.dumps({"revision_id": args.revision, "result": args.mode}, ensure_ascii=False))
    return 0


def inspect_revision_snapshots(root: Path, revisions: list[dict[str, str]]) -> tuple[dict, list[str], list[str]]:
    """Verify durable before-revision archives without treating them as current documents."""
    items: list[dict] = []
    errors: list[str] = []
    warnings: list[str] = []
    allowed_names = set(REVISION_SNAPSHOT_DOCUMENTS)

    for row in revisions:
        revision_id = row.get("revision_id", "")
        if not re.fullmatch(r"R-\d{3,}", revision_id):
            continue  # The revision registry check reports the unsafe/invalid identifier.
        snapshot_relative = f"revisions/{revision_id}-before"
        manifest_relative = f"revisions/{revision_id}-before.manifest.json"
        snapshot = root / snapshot_relative
        manifest_path = root / manifest_relative
        recorded_digest = row.get("snapshot_manifest_sha256", "")
        item = {
            "revision_id": revision_id,
            "kind": "before_revision_archive",
            "snapshot_path": snapshot_relative,
            "manifest_path": manifest_relative if recorded_digest else None,
            "status": "verified",
            "files": [],
            "issues": [],
        }

        def damage(code: str, message: str, path: str | None = None) -> None:
            issue = {"code": code, "message": message}
            if path is not None:
                issue["path"] = path
            item["issues"].append(issue)
            item["status"] = "damaged"
            errors.append(message)

        if not recorded_digest:
            item["status"] = "legacy_unverifiable"
            item["snapshot_present"] = snapshot.is_dir() and not snapshot.is_symlink()
            message = (
                f"{revision_id}: legacy revision без сохранённой описи; наличие и неизменность "
                "архива до исправления не доказаны."
            )
            item["issues"].append({"code": "legacy_no_manifest_evidence", "message": message})
            warnings.append(message)
            items.append(item)
            continue

        if not re.fullmatch(r"[0-9a-f]{64}", recorded_digest):
            damage(
                "manifest_digest_invalid",
                f"{revision_id}: в журнале некорректный hash описи архива до исправления.",
                "revisions/revision-log.csv",
            )
            items.append(item)
            continue
        if manifest_path.is_symlink() or not manifest_path.is_file():
            damage(
                "manifest_missing",
                f"{revision_id}: сохранённая опись архива до исправления отсутствует: {manifest_relative}.",
                manifest_relative,
            )
            items.append(item)
            continue
        if sha256(manifest_path) != recorded_digest:
            damage(
                "manifest_modified",
                f"{revision_id}: сохранённая опись архива до исправления изменена: {manifest_relative}.",
                manifest_relative,
            )
            items.append(item)
            continue
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            damage(
                "manifest_invalid",
                f"{revision_id}: сохранённая опись архива до исправления не читается как JSON: {exc}.",
                manifest_relative,
            )
            items.append(item)
            continue
        if not isinstance(manifest, dict):
            damage(
                "manifest_invalid",
                f"{revision_id}: сохранённая опись архива до исправления должна быть JSON object.",
                manifest_relative,
            )
            items.append(item)
            continue
        if manifest.get("contract") != REVISION_SNAPSHOT_CONTRACT or manifest.get("revision_id") != revision_id or manifest.get("kind") != "before_revision_archive":
            damage(
                "manifest_identity_mismatch",
                f"{revision_id}: сохранённая опись не подтверждает ожидаемый архив до исправления.",
                manifest_relative,
            )
            items.append(item)
            continue
        inventory = manifest.get("files")
        if not isinstance(inventory, dict):
            damage(
                "manifest_invalid",
                f"{revision_id}: в сохранённой описи нет object `files`.",
                manifest_relative,
            )
            items.append(item)
            continue
        unsafe_names = sorted(name for name in inventory if not isinstance(name, str) or name not in allowed_names)
        if unsafe_names:
            damage(
                "manifest_file_name_invalid",
                f"{revision_id}: опись содержит недопустимые имена файлов; произвольные пути не читаются: {unsafe_names!r}.",
                manifest_relative,
            )
        valid_inventory: dict[str, dict] = {}
        for name, record in inventory.items():
            if not isinstance(name, str) or name not in allowed_names:
                continue
            if (not isinstance(record, dict)
                    or not re.fullmatch(r"[0-9a-f]{64}", str(record.get("sha256", "")))
                    or isinstance(record.get("bytes"), bool)
                    or not isinstance(record.get("bytes"), int)
                    or record["bytes"] < 0):
                damage(
                    "manifest_file_record_invalid",
                    f"{revision_id}: опись содержит некорректную запись файла {name}.",
                    manifest_relative,
                )
                continue
            valid_inventory[name] = record
        item["files"] = sorted(valid_inventory)

        if snapshot.is_symlink() or (snapshot.exists() and not snapshot.is_dir()):
            damage(
                "snapshot_not_directory",
                f"{revision_id}: путь архива до исправления не является обычным каталогом: {snapshot_relative}.",
                snapshot_relative,
            )
            items.append(item)
            continue
        if not snapshot.is_dir():
            damage(
                "snapshot_missing",
                f"{revision_id}: каталог архива до исправления отсутствует: {snapshot_relative}.",
                snapshot_relative,
            )
            items.append(item)
            continue
        for name, record in valid_inventory.items():
            archived_relative = f"{snapshot_relative}/{name}"
            archived = snapshot / name  # name was checked against the fixed allow-list above.
            if archived.is_symlink() or not archived.is_file():
                damage(
                    "file_missing",
                    f"{revision_id}: из архива до исправления исчез файл {archived_relative}.",
                    archived_relative,
                )
                continue
            if archived.stat().st_size != record["bytes"] or sha256(archived) != record["sha256"]:
                damage(
                    "file_modified",
                    f"{revision_id}: файл архива до исправления изменён относительно описи: {archived_relative}.",
                    archived_relative,
                )
        items.append(item)

    summary = {
        "scope": "Проверяются только архивы документов до revise; текущие brief/options/strategy/memo/state с ними не сравниваются.",
        "items": items,
        "counts": {
            "verified": sum(item["status"] == "verified" for item in items),
            "damaged": sum(item["status"] == "damaged" for item in items),
            "legacy_unverifiable": sum(item["status"] == "legacy_unverifiable" for item in items),
        },
    }
    return summary, errors, warnings


def check_project(root: Path) -> dict:
    """Return the structural check result without printing or changing the project."""
    errors: list[str] = []
    warnings: list[str] = []
    for relative in REQUIRED_PROJECT_FILES:
        if not (root / relative).is_file():
            errors.append(f"Отсутствует обязательный файл {relative}.")
    metadata = load_json(root / "project.json", {})
    if not isinstance(metadata, dict):
        errors.append("project.json: корень должен быть JSON object.")
        metadata = {}
    schema = metadata.get("schema_version")
    if not isinstance(schema, str) or schema not in {"1.0", "1.1"}:
        errors.append(f"project.json: неподдерживаемая schema_version {schema!r}; поддерживаются строки 1.0 и 1.1.")
    if schema == "1.1" and not (root / "decision-memo.md").is_file():
        errors.append("Отсутствует обязательный для schema 1.1 файл decision-memo.md.")
    artifact_stage = metadata.get("artifact_stage") or "scaffold"
    if metadata.get("artifact_stage") is None:
        warnings.append("project.json: artifact_stage отсутствует; legacy-проект считается scaffold.")
    elif artifact_stage not in ARTIFACT_STAGES:
        errors.append(f"project.json: неизвестный artifact_stage {artifact_stage!r}.")
    for key in ["schema_version", "slug", "title", "created_at", "mode", "business_decision_status"]:
        if not metadata.get(key):
            errors.append(f"project.json: пустое обязательное поле {key}.")
    sources_path = root / "sources" / "index.json"
    sources = load_json(sources_path, []) if sources_path.is_file() else []
    if not isinstance(sources, list):
        errors.append("sources/index.json: корень должен быть JSON array.")
        sources = []
    invalid_source_rows = [index for index, item in enumerate(sources, start=1) if not isinstance(item, dict)]
    if invalid_source_rows:
        errors.append(f"sources/index.json: записи не-object в позициях {invalid_source_rows}.")
        sources = [item for item in sources if isinstance(item, dict)]
    source_ids = {item.get("source_id", "") for item in sources}
    if len(source_ids) != len(sources):
        errors.append("sources/index.json: повторяющиеся source_id.")
    source_locators: dict[str, set[str]] = {}
    for item in sources:
        identifier = item.get("source_id", "?")
        for key in ["source_id", "stored_path", "extract_path", "sha256", "retrieved_at", "permission"]:
            if not item.get(key):
                errors.append(f"Источник {identifier}: пустое поле {key}.")
        if not ID_RE.fullmatch(item.get("source_id") or "") or not (item.get("source_id") or "").startswith("S-"):
            errors.append(f"Источник {identifier}: некорректный source_id.")
        for key in ["stored_path", "extract_path"]:
            path = (root / (item.get(key) or "")).resolve()
            if not path.is_relative_to(root):
                errors.append(f"Источник {identifier}: {key} выходит за каталог проекта.")
                continue
            if not path.is_file():
                errors.append(f"Источник {identifier}: нет {key} {path}.")
        stored = (root / (item.get("stored_path") or "")).resolve()
        if stored.is_relative_to(root) and stored.is_file() and item.get("sha256") != sha256(stored):
            errors.append(f"Источник {identifier}: hash не совпадает с оригиналом; нужен явный revision/re-ingest.")
        extract = (root / (item.get("extract_path") or "")).resolve()
        if extract.is_relative_to(root) and extract.is_file():
            if item.get("extract_sha256"):
                if item["extract_sha256"] != sha256(extract):
                    errors.append(f"Источник {identifier}: hash извлечения не совпадает; извлечение нельзя редактировать молча.")
            else:
                warnings.append(f"Источник {identifier}: legacy-запись без extract_sha256; целостность извлечения не доказана.")
            locators = set(re.findall(r"^- `([^`]+)` —", extract.read_text(encoding="utf-8"), flags=re.MULTILINE))
            source_locators[identifier] = locators
        if item.get("gaps"):
            warnings.append(f"Источник {identifier}: есть пробелы извлечения ({len(item['gaps'])}).")
    claims_path = root / "evidence" / "claims.csv"
    claims = read_rows(claims_path)
    claim_ids = {row.get("claim_id", "") for row in claims}
    if len(claim_ids) != len(claims):
        errors.append("claims.csv: повторяющиеся claim_id.")
    for row in claims:
        identifier = row.get("claim_id", "?")
        for key in ["claim_id", "type", "statement", "status"]:
            if not row.get(key):
                errors.append(f"{identifier}: пустое обязательное поле claim {key}.")
        if not re.fullmatch(r"E-\d{3,}", row.get("claim_id") or ""):
            errors.append(f"{identifier}: некорректный claim_id.")
        if row.get("type") not in CLAIM_TYPES:
            errors.append(f"{identifier}: неизвестный type {row.get('type')!r}.")
        if row.get("status") not in CLAIM_STATUSES:
            errors.append(f"{identifier}: неизвестный status {row.get('status')!r}.")
        refs = {value.strip() for value in (row.get("source_ids") or "").split(";") if value.strip()}
        missing = refs - source_ids
        if missing:
            errors.append(f"{identifier}: неизвестные источники {sorted(missing)}.")
        if row.get("type") == "fact" and row.get("status") == "active" and (not refs or not row.get("locator")):
            errors.append(f"{identifier}: активному факту нужны source_ids и locator.")
        locator_value = row.get("locator") or ""
        if locator_value:
            locator_parts = [part.strip() for part in locator_value.split(";") if part.strip()]
            qualified: dict[str, list[str]] = {}
            valid_qualified = True
            for part in locator_parts:
                match = re.fullmatch(r"(S-\d{3,})#(.+)", part)
                if not match:
                    valid_qualified = False
                    break
                qualified.setdefault(match.group(1), []).append(match.group(2))
            if not valid_qualified:
                warnings.append(f"{identifier}: legacy/complex locator не проверен; новый формат `S-001#locator;S-002#locator`.")
            else:
                for source_id in refs:
                    if source_id not in qualified:
                        errors.append(f"{identifier}: для {source_id} нет source-qualified locator.")
                for source_id, locators in qualified.items():
                    if source_id not in refs:
                        errors.append(f"{identifier}: locator ссылается на {source_id}, которого нет в source_ids.")
                    for locator in locators:
                        if source_id in source_locators and locator not in source_locators[source_id]:
                            errors.append(f"{identifier}: locator {source_id}#{locator} отсутствует в сохранённом извлечении.")
    conclusions_path = root / "evidence" / "conclusions.csv"
    conclusions = read_rows(conclusions_path)
    conclusion_ids = {row.get("conclusion_id", "") for row in conclusions}
    if len(conclusion_ids) != len(conclusions):
        errors.append("conclusions.csv: повторяющиеся conclusion_id.")
    for row in conclusions:
        identifier = row.get("conclusion_id", "?")
        for key in ["conclusion_id", "statement", "status", "review_needed"]:
            if not row.get(key):
                errors.append(f"{identifier}: пустое обязательное поле conclusion {key}.")
        if not re.fullmatch(r"C-\d{3,}", row.get("conclusion_id") or ""):
            errors.append(f"{identifier}: некорректный conclusion_id.")
        if row.get("status") not in CLAIM_STATUSES:
            errors.append(f"{identifier}: неизвестный status вывода {row.get('status')!r}.")
        if row.get("review_needed") not in {"yes", "no"}:
            errors.append(f"{identifier}: review_needed должен быть yes/no.")
        refs = {value.strip() for value in (row.get("evidence_ids") or "").split(";") if value.strip()}
        if refs - claim_ids:
            errors.append(f"{identifier}: неизвестные evidence_ids {sorted(refs - claim_ids)}.")
        if row.get("status") == "active" and not refs:
            warnings.append(f"{identifier}: активный вывод не имеет evidence_ids; checker не доказывает его обоснованность.")
        if row.get("review_needed") == "yes":
            warnings.append(f"{identifier}: требуется пересмотр.")
    decisions = read_rows(root / "decisions" / "decisions.csv")
    decision_ids = {row.get("decision_id", "") for row in decisions}
    if len(decision_ids) != len(decisions):
        errors.append("decisions.csv: повторяющиеся decision_id.")
    for row in decisions:
        identifier = row.get("decision_id", "?")
        for key in ["decision_id", "recorded_at", "decision_kind", "status"]:
            if not row.get(key):
                errors.append(f"{identifier}: пустое обязательное поле decision {key}.")
        if not re.fullmatch(r"D-\d{3,}", row.get("decision_id") or ""):
            errors.append(f"{identifier}: некорректный decision_id.")
        try:
            if row.get("recorded_at"):
                dt.datetime.fromisoformat(row["recorded_at"])
        except ValueError:
            errors.append(f"{identifier}: recorded_at не ISO 8601.")
        if row.get("status") not in DECISION_STATUSES:
            errors.append(f"{identifier}: неизвестный status решения {row.get('status')!r}.")
        if row.get("decision_kind") not in DECISION_KINDS:
            errors.append(f"{row.get('decision_id', '?')}: неизвестный decision_kind {row.get('decision_kind')!r}.")
        refs = {value.strip() for value in (row.get("conclusion_ids") or "").split(";") if value.strip()}
        if refs - conclusion_ids:
            errors.append(f"{row.get('decision_id', '?')}: неизвестные conclusion_ids {sorted(refs - conclusion_ids)}.")
        if row.get("status") == "accepted" and not row.get("decider"):
            errors.append(f"{identifier}: принятое решение не имеет decider.")
        if row.get("status") == "accepted" and row.get("decision_kind") != "human":
            errors.append(f"{identifier}: accepted status требует human decision_kind.")
        if row.get("status") == "accepted":
            for key in ["chosen_option", "conclusion_ids"]:
                if not row.get(key):
                    errors.append(f"{identifier}: accepted human decision требует {key}.")
        if row.get("status") == "simulated" and row.get("decision_kind") != "simulated":
            errors.append(f"{identifier}: simulated status требует simulated decision_kind.")
    commitments = read_rows(root / "commitments.csv")
    commitment_ids = {row.get("commitment_id", "") for row in commitments}
    if len(commitment_ids) != len(commitments):
        errors.append("commitments.csv: повторяющиеся commitment_id.")
    for row in commitments:
        identifier = row.get("commitment_id", "?")
        for key in ["commitment_id", "description", "status"]:
            if not row.get(key):
                errors.append(f"{identifier}: пустое обязательное поле commitment {key}.")
        if not re.fullmatch(r"K-\d{3,}", row.get("commitment_id") or ""):
            errors.append(f"{identifier}: некорректный commitment_id.")
        if row.get("status") not in COMMITMENT_STATUSES:
            errors.append(f"{identifier}: неизвестный status обязательства {row.get('status')!r}.")
        if row.get("decision_id") and row.get("decision_id") not in decision_ids:
            errors.append(f"{identifier}: неизвестный decision_id {row.get('decision_id')}.")
        if row.get("status") in {"confirmed", "in_progress", "done", "overdue"}:
            for key in ["decision_id", "owner", "confirmed_by", "confirmed_at"]:
                if not row.get(key):
                    errors.append(f"{identifier}: статус {row.get('status')} требует {key}.")
            related = next((decision for decision in decisions if decision.get("decision_id") == row.get("decision_id")), None)
            if related and (related.get("status") != "accepted" or related.get("decision_kind") != "human"):
                errors.append(f"{identifier}: подтверждённое обязательство должно ссылаться на accepted human decision.")
    revisions = read_rows(root / "revisions" / "revision-log.csv")
    revision_ids = {row.get("revision_id", "") for row in revisions}
    if len(revision_ids) != len(revisions):
        errors.append("revision-log.csv: повторяющиеся revision_id.")
    for row in revisions:
        identifier = row.get("revision_id", "?")
        for key in ["revision_id", "recorded_at", "old_claim_id", "old_status", "new_status", "reason", "human_review_required"]:
            if not row.get(key):
                errors.append(f"{identifier}: пустое обязательное поле revision {key}.")
        if not row.get("evidence_action"):
            warnings.append(f"{identifier}: legacy revision без evidence_action; способ reuse citations не доказан записью.")
        if not re.fullmatch(r"R-\d{3,}", row.get("revision_id") or ""):
            errors.append(f"{identifier}: некорректный revision_id.")
        try:
            if row.get("recorded_at"):
                dt.datetime.fromisoformat(row["recorded_at"])
        except ValueError:
            errors.append(f"{identifier}: recorded_at не ISO 8601.")
        if row.get("old_status") not in CLAIM_STATUSES or row.get("new_status") not in CLAIM_STATUSES:
            errors.append(f"{identifier}: неизвестный old_status/new_status revision.")
        if row.get("human_review_required") not in {"yes", "no"}:
            errors.append(f"{identifier}: human_review_required должен быть yes/no.")
        if row.get("old_claim_id") not in claim_ids:
            errors.append(f"{identifier}: неизвестный old_claim_id {row.get('old_claim_id')}.")
        if row.get("new_claim_id") and row.get("new_claim_id") not in claim_ids:
            errors.append(f"{identifier}: неизвестный new_claim_id {row.get('new_claim_id')}.")
        affected_conclusions = {value for value in (row.get("affected_conclusions") or "").split(";") if value}
        affected_decisions = {value for value in (row.get("affected_decisions") or "").split(";") if value}
        affected_commitments = {value for value in (row.get("affected_commitments") or "").split(";") if value}
        if affected_conclusions - conclusion_ids:
            errors.append(f"{identifier}: неизвестные affected_conclusions {sorted(affected_conclusions - conclusion_ids)}.")
        if affected_decisions - decision_ids:
            errors.append(f"{identifier}: неизвестные affected_decisions {sorted(affected_decisions - decision_ids)}.")
        if affected_commitments - commitment_ids:
            errors.append(f"{identifier}: неизвестные affected_commitments {sorted(affected_commitments - commitment_ids)}.")
    revision_snapshots, snapshot_errors, snapshot_warnings = inspect_revision_snapshots(root, revisions)
    errors.extend(snapshot_errors)
    warnings.extend(snapshot_warnings)
    operations = read_rows(root / "runs" / "operations.csv")
    operation_ids = {row.get("operation_id", "") for row in operations}
    if len(operation_ids) != len(operations):
        errors.append("operations.csv: повторяющиеся operation_id.")
    resolutions = {row.get("related_operation_id"): row for row in operations if row.get("related_operation_id")}
    for row in operations:
        identifier = row.get("operation_id", "?")
        for key in ["operation_id", "started_at", "status", "tool", "cost_status"]:
            if not row.get(key):
                errors.append(f"{identifier}: пустое обязательное поле operation {key}.")
        if not re.fullmatch(r"OP-\d{3,}", row.get("operation_id") or ""):
            errors.append(f"{identifier}: некорректный operation_id.")
        for date_field in ["started_at", "finished_at"]:
            try:
                if row.get(date_field):
                    dt.datetime.fromisoformat(row[date_field])
            except ValueError:
                errors.append(f"{identifier}: {date_field} не ISO 8601.")
        if row.get("status") in {"succeeded", "failed", "outcome_unknown"} and not row.get("finished_at"):
            errors.append(f"{identifier}: завершённая операция требует finished_at.")
        if row.get("status") not in OP_STATUSES:
            errors.append(f"{identifier}: неизвестный статус операции.")
        if row.get("cost_status") not in COST_STATUSES:
            errors.append(f"{row.get('operation_id', '?')}: неизвестный cost_status.")
        if row.get("status") == "in_progress":
            warnings.append(f"{row.get('operation_id', '?')}: операция не завершена; после сбоя выполните recover.")
        if row.get("status") == "outcome_unknown":
            if identifier in resolutions:
                warnings.append(f"{identifier}: исход исторически неизвестен; отдельная resolution запись {resolutions[identifier].get('operation_id')} сохранена.")
            else:
                warnings.append(f"{identifier}: исход неизвестен; не повторять без проверки.")
        if row.get("cost_status") == "unknown":
            warnings.append(f"{row.get('operation_id', '?')}: стоимость неизвестна.")
        if row.get("cost_status") == "known" and (not row.get("cost_amount") or not row.get("currency")):
            errors.append(f"{identifier}: known cost требует amount и currency.")
        if row.get("related_operation_id"):
            related = next((candidate for candidate in operations if candidate.get("operation_id") == row.get("related_operation_id")), None)
            if not related or related.get("status") != "outcome_unknown":
                errors.append(f"{identifier}: resolution должна ссылаться на outcome_unknown operation.")
            if row.get("resolution") not in {"confirmed_succeeded", "confirmed_failed", "still_unknown"}:
                errors.append(f"{identifier}: неизвестное resolution {row.get('resolution')!r}.")
    for pending in sorted((root / "sources" / ".staging").glob("S-*.pending.json")) if (root / "sources" / ".staging").exists() else []:
        errors.append(f"Незавершённый ingest: {pending.relative_to(root)}; используйте ingest-recover.")
    for pending in sorted((root / "revisions").glob(".pending-R-*.json")) if (root / "revisions").exists() else []:
        errors.append(f"Незавершённый revision: {pending.relative_to(root)}; используйте revision-recover.")
    ingest_failures = read_rows(root / "runs" / "ingest-failures.csv")
    if ingest_failures:
        warnings.append(f"Зафиксированы failed ingest attempts: {len(ingest_failures)}; они не считаются источниками.")
    stage_labels = {"scaffold": "только scaffold", "working": "рабочее исследование", "decision_draft": "черновик решения", "decision_recorded": "решение записано"}
    if artifact_stage == "decision_recorded" and not any(row.get("status") in {"accepted", "rejected", "simulated"} for row in decisions):
        errors.append("artifact_stage=decision_recorded, но нет записанного accepted/rejected/simulated decision.")
    recorded_human_decision = any(row.get("decision_kind") == "human" and row.get("status") in {"accepted", "rejected"} for row in decisions)
    result = {"ok": not errors, "structural_only": True,
              "completion": {"artifact_stage": artifact_stage, "label": stage_labels.get(artifact_stage, "unknown"),
                             "has_recorded_human_decision": recorded_human_decision,
                             "is_completed_decision": artifact_stage == "decision_recorded" and recorded_human_decision and not errors,
                             "not_proven": "Смысловая поддержка claims, качество вариантов и стратегии кодом не проверяются."},
              "errors": errors, "warnings": warnings,
              "revision_snapshots": revision_snapshots,
              "counts": {"sources": len(sources), "claims": len(claims), "conclusions": len(conclusions), "decisions": len(decisions), "commitments": len(commitments), "revisions": len(revisions), "operations": len(operations), "ingest_failures": len(ingest_failures)}}
    return result


def command_check(args: argparse.Namespace) -> int:
    result = check_project(project_root(args.project))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 1


RESUME_ITEM_LIMIT = 8


def cold_resume_text(path: Path) -> str | None:
    """Read the authored cold-resume section without interpreting its claims."""
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    start = next((index for index, line in enumerate(lines) if re.match(r"^##\s+Cold resume\b", line, re.IGNORECASE)), None)
    if start is None:
        return None  # Some valid projects predate the heading. Keep their observed facts.
    end = next((index for index in range(start + 1, len(lines)) if re.match(r"^##\s+", lines[index])), len(lines))
    return "\n".join(lines[start:end]).strip()


def resume_locator(relative: str, id_field: str, row: dict[str, str]) -> str:
    identifier = row.get(id_field)
    return f"{relative}#{id_field}={identifier}" if identifier else relative


def limited_resume_rows(rows: list[dict], *, relative: str, id_field: str, fields: tuple[str, ...], limit: int = RESUME_ITEM_LIMIT) -> dict:
    selected = rows[-limit:]
    items = []
    for row in selected:
        item = {field: row.get(field, "") for field in fields}
        item["record"] = resume_locator(relative, id_field, row)
        items.append(item)
    return {"path": relative, "items": items, "omitted": max(0, len(rows) - len(selected))}


def limited_resume_paths(paths: list[str], limit: int = RESUME_ITEM_LIMIT) -> dict:
    selected = paths[-limit:]
    return {"paths": selected, "omitted": max(0, len(paths) - len(selected))}


def read_resume_registry(path: Path, required_headers: tuple[str, ...]) -> list[dict[str, str]]:
    """Use the canonical CSV reader, but refuse a missing/ambiguous resume schema."""
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, strict=True)
        headers = reader.fieldnames
        rows = list(reader)
    if not headers:
        raise ValueError(f"{path}: CSV не содержит заголовок; resume не подставляет пустой реестр.")
    missing = [header for header in required_headers if header not in headers]
    if missing:
        raise ValueError(f"{path}: нет обязательных колонок resume: {', '.join(missing)}.")
    if len(headers) != len(set(headers)) or any(None in row or None in row.values() for row in rows):
        raise ValueError(f"{path}: повтор колонок или неверная ширина строки CSV; запись неоднозначна.")
    return rows


def command_resume(args: argparse.Namespace) -> int:
    root = project_root(args.project)
    check = check_project(root)
    metadata = load_json(root / "project.json", None)
    if not isinstance(metadata, dict):
        raise ValueError("project.json: корень должен быть JSON object; resume не может собрать проектные факты.")

    registry_paths = {
        "decisions": root / "decisions" / "decisions.csv",
        "commitments": root / "commitments.csv",
        "conclusions": root / "evidence" / "conclusions.csv",
        "operations": root / "runs" / "operations.csv",
        "ingest_failures": root / "runs" / "ingest-failures.csv",
    }
    missing = [path.relative_to(root).as_posix() for path in registry_paths.values() if not path.is_file()]
    if not (root / "state.md").is_file():
        missing.append("state.md")
    if missing:
        print(json.dumps({
            "ok": False,
            "error": "resume не собран: отсутствуют канонические файлы; пустые значения не подставлены.",
            "missing": missing,
            "structural_check": check,
        }, ensure_ascii=False, indent=2))
        return 1

    decisions = read_resume_registry(registry_paths["decisions"], ("decision_id", "decision_kind", "status"))
    commitments = read_resume_registry(registry_paths["commitments"], ("commitment_id", "status"))
    conclusions = read_resume_registry(registry_paths["conclusions"], ("conclusion_id", "status", "review_needed"))
    operations = read_resume_registry(registry_paths["operations"], ("operation_id", "status", "cost_status"))
    ingest_failures = read_resume_registry(registry_paths["ingest_failures"], ("failure_id", "status", "error"))
    resolutions = {row["related_operation_id"]: row.get("resolution") for row in operations if row.get("related_operation_id")}
    unresolved_operations = [
        row for row in operations
        if row.get("status") in {"planned", "in_progress"}
        or (row.get("status") == "outcome_unknown" and resolutions.get(row.get("operation_id")) not in {"confirmed_succeeded", "confirmed_failed"})
    ]
    failed_operations = [row for row in operations if row.get("status") == "failed"]
    pending_ingests = [
        path.relative_to(root).as_posix()
        for path in sorted((root / "sources" / ".staging").glob("S-*.pending.json"))
    ] if (root / "sources" / ".staging").exists() else []
    pending_revisions = [
        path.relative_to(root).as_posix()
        for path in sorted((root / "revisions").glob(".pending-R-*.json"))
    ] if (root / "revisions").exists() else []

    checkpoint = cold_resume_text(root / "state.md")
    result = {
        "contract": "strategist.resume/1.0",
        "ok": check["ok"],
        "project": {
            "schema_version": metadata.get("schema_version"),
            "slug": metadata.get("slug"),
            "title": metadata.get("title"),
            "artifact_stage": metadata.get("artifact_stage", "scaffold"),
            "business_decision_status": metadata.get("business_decision_status"),
            "record": "project.json",
        },
        "authored_checkpoint": {
            "kind": "authored_not_observed" if checkpoint is not None else "section_not_recorded",
            "path": "state.md",
            "text": checkpoint,
        },
        "observed_facts": {
            "decisions": limited_resume_rows(
                decisions, relative="decisions/decisions.csv", id_field="decision_id",
                fields=("decision_id", "recorded_at", "decider", "decision_kind", "status", "chosen_option", "revisit_on", "revisit_if")),
            "commitments": limited_resume_rows(
                commitments, relative="commitments.csv", id_field="commitment_id",
                fields=("commitment_id", "decision_id", "description", "owner", "status", "due_on", "review_condition")),
            "conclusions": limited_resume_rows(
                conclusions, relative="evidence/conclusions.csv", id_field="conclusion_id",
                fields=("conclusion_id", "statement", "evidence_ids", "change_condition", "status", "review_needed")),
        },
        "recovery_and_errors": {
            "unresolved_operations": limited_resume_rows(
                unresolved_operations, relative="runs/operations.csv", id_field="operation_id",
                fields=("operation_id", "started_at", "status", "tool", "artifact", "cost_status", "related_operation_id", "resolution", "notes")),
            "failed_operations": limited_resume_rows(
                failed_operations, relative="runs/operations.csv", id_field="operation_id",
                fields=("operation_id", "started_at", "finished_at", "status", "tool", "artifact", "cost_status", "notes")),
            "ingest_failures": limited_resume_rows(
                ingest_failures, relative="runs/ingest-failures.csv", id_field="failure_id",
                fields=("failure_id", "recorded_at", "source_id", "input", "status", "cost_status", "error")),
            "pending_ingests": limited_resume_paths(pending_ingests),
            "pending_revisions": limited_resume_paths(pending_revisions),
        },
        "structural_check": {
            "ok": check["ok"],
            "errors": check["errors"],
            "warnings": check["warnings"],
            "revision_snapshots": check["revision_snapshots"],
            "reproduce_with": "python3 tools/strategist.py check " + str(root),
        },
        "read_full_artifacts": ["brief.md", "options.md", "strategy.md"]
        + (["decision-memo.md"] if (root / "decision-memo.md").is_file() else []),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if check["ok"] else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", action="version", version=VERSION)
    sub = parser.add_subparsers(dest="command", required=True)
    doctor = sub.add_parser("doctor", help="Проверить локальные зависимости")
    doctor.set_defaults(func=command_doctor)
    init = sub.add_parser("init", help="Создать состояние нового кейса")
    init.add_argument("directory"); init.add_argument("--slug", required=True); init.add_argument("--title"); init.add_argument("--allow-existing", action="store_true"); init.set_defaults(func=command_init)
    ingest = sub.add_parser("ingest", help="Сохранить и адресно извлечь разрешённый источник")
    ingest.add_argument("project"); ingest.add_argument("input"); ingest.add_argument("--title"); ingest.add_argument("--permission", default="owner-provided", choices=["owner-provided", "open-public", "licensed", "synthetic"]); ingest.add_argument("--synthetic", action="store_true"); ingest.set_defaults(func=command_ingest)
    ingest_recover = sub.add_parser("ingest-recover", help="Завершить или удалить явно выбранный pending ingest")
    ingest_recover.add_argument("project"); ingest_recover.add_argument("--source-id", required=True); ingest_recover.add_argument("--mode", choices=["complete", "discard"], required=True); ingest_recover.set_defaults(func=command_ingest_recover)
    profile = sub.add_parser("profile", help="Детерминированный профиль CSV")
    profile.add_argument("csv"); profile.add_argument("--output", required=True); profile.set_defaults(func=command_profile)
    retention = sub.add_parser("retention", help="Посчитать retention по готовым агрегатам")
    retention.add_argument("csv"); retention.add_argument("--cohort", default="cohort"); retention.add_argument("--period", default="period"); retention.add_argument("--active", default="active_users"); retention.add_argument("--size", default="cohort_size"); retention.add_argument("--output", required=True); retention.set_defaults(func=command_retention)
    operation = sub.add_parser("operation", help="Учесть операцию, исход и стоимость")
    operation.add_argument("project"); operation.add_argument("action", choices=["start", "finish", "fail", "unknown", "resolve"]); operation.add_argument("--id"); operation.add_argument("--tool", default="manual-or-agent"); operation.add_argument("--inputs", default=""); operation.add_argument("--artifact", default=""); operation.add_argument("--cost-status", default="unknown", choices=sorted(COST_STATUSES)); operation.add_argument("--cost-amount", default=""); operation.add_argument("--currency", default=""); operation.add_argument("--human-minutes", default=""); operation.add_argument("--resolution", choices=["confirmed_succeeded", "confirmed_failed", "still_unknown"]); operation.add_argument("--notes", default=""); operation.set_defaults(func=command_operation)
    recover = sub.add_parser("recover", help="После прерывания пометить незавершённые операции неизвестными")
    recover.add_argument("project"); recover.set_defaults(func=command_recover)
    revise = sub.add_parser("revise", help="Отозвать/заменить утверждение и построить карту влияния")
    revise.add_argument("project"); revise.add_argument("--claim", required=True); revise.add_argument("--status", choices=["disputed", "retracted", "superseded"], default="retracted"); revise.add_argument("--reason", required=True); revise.add_argument("--new-statement"); revise.add_argument("--type", choices=sorted(CLAIM_TYPES)); revise.add_argument("--source-ids"); revise.add_argument("--locator"); revise.add_argument("--reuse-evidence", action="store_true"); revise.add_argument("--reuse-reason"); revise.add_argument("--period"); revise.add_argument("--unit"); revise.add_argument("--limitations", default=""); revise.add_argument("--allow-nonactive", action="store_true"); revise.set_defaults(func=command_revise)
    revision_recover = sub.add_parser("revision-recover", help="Завершить или откатить явно выбранный pending revision")
    revision_recover.add_argument("project"); revision_recover.add_argument("--revision", required=True); revision_recover.add_argument("--mode", choices=["complete", "rollback"], required=True); revision_recover.set_defaults(func=command_revision_recover)
    resume = sub.add_parser("resume", help="Собрать read-only JSON для продолжения в новом чате")
    resume.add_argument("project"); resume.set_defaults(func=command_resume)
    check = sub.add_parser("check", help="Проверить ссылки, hash, состояния и неизвестные исходы")
    check.add_argument("project"); check.set_defaults(func=command_check)
    return parser


def main() -> int:
    try:
        args = build_parser().parse_args()
        return args.func(args)
    except (ValueError, OSError, csv.Error) as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
