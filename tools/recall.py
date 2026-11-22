#!/usr/bin/env python3
"""Offline recall by meaning for curated precedents and one case's registries.

Method (disclosed in every answer): Russian/English word stems plus a curated
concept lexicon (``tools/recall_lexicon.json``). A query word counts as covered
when the card has the same stem or shares one of the word's concepts. The score
is the weighted share of covered query words. No embeddings, network or model
calls. Out-of-lexicon synonyms are found only if the stems coincide.

Run from the repository root:

    python3 tools/recall.py precedents "почему уходят клиенты после промо"
    python3 tools/recall.py case examples/demo "обещали живого преподавателя"
    python3 tools/recall.py analyze "churn после рекламной кампании"
    python3 tools/recall.py eval docs/mcp-recall/eval
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
import json
from pathlib import Path
import re
import sys
from typing import Any, Iterable

TOOLS = Path(__file__).resolve().parent
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import case_scope  # noqa: E402
import precedent  # noqa: E402

LEXICON_PATH = TOOLS / "recall_lexicon.json"
LEXICON_SCHEMA = "strategist.recall-lexicon/1"
METHOD = "strategist.recall/1"
STRONG = 0.75
PARTIAL = 0.5
UNKNOWN_WORD_WEIGHT = 0.8
BROAD_WEIGHT_CAP = 0.5
MAX_QUERY_CHARS = 500
MAX_QUERY_TOKENS = 60
DEFAULT_LIMIT = 5
MAX_LIMIT = 10

TOKEN_RE = re.compile(r"[0-9a-zа-я]+")

# ---------------------------------------------------------------- stemming

_RU_VOWELS = frozenset("аеиоуыэюя")
_PERFECTIVE_GERUND = ((("вшись", "вши", "в"), True), (("ившись", "ывшись", "ивши", "ывши", "ив", "ыв"), False))
_ADJECTIVE = ((("ими", "ыми", "его", "ого", "ему", "ому", "ее", "ие", "ые", "ое", "ей", "ий", "ый", "ой", "ем",
                "им", "ым", "ом", "их", "ых", "ую", "юю", "ая", "яя", "ою", "ею"), False),)
_PARTICIPLE = ((("ем", "нн", "вш", "ющ", "щ"), True), (("ивш", "ывш", "ующ"), False))
_REFLEXIVE = ((("ся", "сь"), False),)
_VERB = ((("ла", "на", "ете", "йте", "ли", "й", "л", "ем", "н", "ло", "но", "ет", "ют", "ны", "ть", "ешь", "нно"), True),
         (("ила", "ыла", "ена", "ейте", "уйте", "ите", "или", "ыли", "ей", "уй", "ил", "ыл", "им", "ым", "ен", "ило",
           "ыло", "ено", "ят", "ует", "уют", "ит", "ыт", "ены", "ить", "ыть", "ишь", "ую", "ю"), False))
_NOUN = ((("а", "ев", "ов", "ие", "ье", "е", "иями", "ями", "ами", "еи", "ии", "и", "ией", "ей", "ой", "ий", "й",
           "иям", "ям", "ием", "ем", "ам", "ом", "о", "у", "ах", "иях", "ях", "ы", "ь", "ию", "ью", "ю", "ия", "ья",
           "я"), False),)
_SUPERLATIVE = ((("ейше", "ейш"), False),)


def _among(region: str, groups) -> int:
    """Snowball 'among': take the longest listed ending; group-1 endings need а/я before them."""
    best = ""
    needs_a = False
    for endings, condition in groups:
        for ending in endings:
            if len(ending) > len(best) and region.endswith(ending):
                best, needs_a = ending, condition
    if not best:
        return 0
    if needs_a:
        index = len(region) - len(best) - 1
        if index < 0 or region[index] not in "ая":
            return 0
    return len(best)


def stem_ru(word: str) -> str:
    """Snowball Russian stemmer (RV/R2 regions, steps 1-4)."""
    rv = next((index + 1 for index, char in enumerate(word) if char in _RU_VOWELS), len(word))
    r1 = next((index + 1 for index in range(1, len(word)) if word[index] not in _RU_VOWELS and word[index - 1] in _RU_VOWELS), len(word))
    r2 = next((index + 1 for index in range(r1 + 1, len(word)) if word[index] not in _RU_VOWELS and word[index - 1] in _RU_VOWELS), len(word))
    head, region = word[:rv], word[rv:]
    removed = _among(region, _PERFECTIVE_GERUND)
    if removed:
        region = region[:-removed]
    else:
        removed = _among(region, _REFLEXIVE)
        if removed:
            region = region[:-removed]
        removed = _among(region, _ADJECTIVE)
        if removed:
            region = region[:-removed]
            removed = _among(region, _PARTICIPLE)
            if removed:
                region = region[:-removed]
        else:
            removed = _among(region, _VERB) or _among(region, _NOUN)
            if removed:
                region = region[:-removed]
    if region.endswith("и"):
        region = region[:-1]
    for ending in ("ость", "ост"):
        if region.endswith(ending) and len(head) + len(region) - len(ending) >= r2:
            region = region[: -len(ending)]
            break
    if region.endswith("нн"):
        region = region[:-1]
    else:
        removed = _among(region, _SUPERLATIVE)
        if removed:
            region = region[:-removed]
            if region.endswith("нн"):
                region = region[:-1]
        elif region.endswith("ь"):
            region = region[:-1]
    return head + region


def stem_en(word: str) -> str:
    """A deliberately small English suffix stripper; the lexicon lists irregular forms."""
    if word.endswith("ies") and len(word) > 4:
        word = word[:-3] + "y"
    elif word.endswith("sses"):
        word = word[:-2]
    elif word.endswith("s") and not word.endswith(("ss", "us", "is")) and len(word) > 3:
        word = word[:-1]
    if word.endswith("ing") and len(word) > 5:
        word = word[:-3]
    elif word.endswith("ed") and len(word) > 4:
        word = word[:-2]
    if word.endswith("e") and len(word) > 4:
        word = word[:-1]
    return word


def normalize(text: str) -> str:
    return text.casefold().replace("ё", "е")


def stem(token: str) -> str:
    if len(token) <= 3 or token.isdigit():
        return token
    if re.search(r"[а-я]", token):
        return stem_ru(token)
    return stem_en(token)


def tokens(text: str) -> list[str]:
    return [token for token in TOKEN_RE.findall(normalize(text)) if len(token) >= 2]


# ---------------------------------------------------------------- lexicon


@dataclass(frozen=True)
class Concept:
    name: str
    label: str
    weight: float
    broad: bool


@dataclass
class Lexicon:
    concepts: dict[str, Concept]
    stems: dict[str, set[str]]
    prefixes: list[tuple[str, str]]
    phrases: list[tuple[tuple[tuple[str, str], ...], str]]
    stop_surface: frozenset[str]
    stop_stems: frozenset[str]
    digest: str
    scope: str

    def is_stop(self, token: str) -> bool:
        return token in self.stop_surface or stem(token) in self.stop_stems

    def token_weight(self, concepts: Iterable[str]) -> float:
        weights = [min(self.concepts[name].weight, BROAD_WEIGHT_CAP) if self.concepts[name].broad
                   else self.concepts[name].weight for name in concepts]
        return max(weights) if weights else UNKNOWN_WORD_WEIGHT


def _phrase_elements(text: str, *, last_is_prefix: bool = False) -> tuple[tuple[str, str], ...]:
    parts = tokens(text) if not last_is_prefix else [part for part in re.split(r"[\s\-]+", normalize(text)) if part]
    elements = [("stem", stem(part)) for part in parts]
    if last_is_prefix and elements:
        elements[-1] = ("prefix", parts[-1])
    return tuple(elements)


def load_lexicon(path: Path = LEXICON_PATH) -> Lexicon:
    import hashlib

    raw = path.read_bytes()
    data = json.loads(raw.decode("utf-8"))
    if data.get("schema") != LEXICON_SCHEMA or not isinstance(data.get("concepts"), dict):
        raise ValueError(f"{path.name}: неподдерживаемый словарь понятий")
    concepts: dict[str, Concept] = {}
    stems: dict[str, set[str]] = {}
    prefixes: list[tuple[str, str]] = []
    phrases: list[tuple[tuple[tuple[str, str], ...], str]] = []
    for name, spec in data["concepts"].items():
        weight = float(spec.get("weight", 1.0))
        if not 0 < weight <= 1:
            raise ValueError(f"{path.name}: вес понятия {name} вне (0, 1]")
        concepts[name] = Concept(name, str(spec.get("label") or name), weight, bool(spec.get("broad")))
        for term in spec.get("terms", []):
            parts = tokens(term)
            if len(parts) == 1:
                stems.setdefault(stem(parts[0]), set()).add(name)
            elif parts:
                phrases.append((_phrase_elements(term), name))
        for prefix in spec.get("prefixes", []):
            parts = [part for part in re.split(r"[\s\-]+", normalize(prefix)) if part]
            if len(parts) == 1:
                if len(parts[0]) < 4:
                    raise ValueError(f"{path.name}: префикс {prefix!r} короче 4 символов")
                prefixes.append((parts[0], name))
            elif parts:
                phrases.append((_phrase_elements(prefix, last_is_prefix=True), name))
        for phrase in spec.get("phrases", []):
            elements = _phrase_elements(phrase)
            if elements:
                phrases.append((elements, name))
    stop_surface = frozenset(normalize(word) for word in data.get("stopwords", []))
    stop_stems = frozenset(stem(word) for word in stop_surface if len(word) > 3)
    return Lexicon(concepts, stems, prefixes, phrases, stop_surface, stop_stems,
                   "sha256:" + hashlib.sha256(raw).hexdigest(), str(data.get("scope", "")))


_LEXICON: Lexicon | None = None


def lexicon() -> Lexicon:
    global _LEXICON
    if _LEXICON is None:
        _LEXICON = load_lexicon()
    return _LEXICON


# ---------------------------------------------------------------- analysis


@dataclass
class Analysis:
    words: list[str]
    stems: list[str]
    content: dict[str, str] = field(default_factory=dict)            # stem -> first surface form
    concepts: dict[str, set[str]] = field(default_factory=dict)      # concept -> surface terms
    stem_concepts: dict[str, set[str]] = field(default_factory=dict)  # content stem -> concepts


def analyze(text: str, lex: Lexicon | None = None) -> Analysis:
    lex = lex or lexicon()
    words = tokens(text)[: MAX_QUERY_TOKENS * 20]
    stems_ = [stem(word) for word in words]
    result = Analysis(words, stems_)
    per_position: list[set[str]] = [set() for _ in words]
    for index, (word, word_stem) in enumerate(zip(words, stems_)):
        if lex.is_stop(word):
            continue
        per_position[index] |= lex.stems.get(word_stem, set())
        for prefix, concept in lex.prefixes:
            if word.startswith(prefix):
                per_position[index].add(concept)
    # A matched phrase fixes the sense of its words: "уходил в минус" is economics, not churn.
    phrase_concepts: list[set[str]] = [set() for _ in words]
    anchors: set[int] = set()
    for elements, concept in lex.phrases:
        width = len(elements)
        for start in range(0, len(words) - width + 1):
            if all((kind == "stem" and stems_[start + offset] == value)
                   or (kind == "prefix" and words[start + offset].startswith(value))
                   for offset, (kind, value) in enumerate(elements)):
                anchors.add(start)
                for offset in range(width):
                    phrase_concepts[start + offset].add(concept)
    for index, concepts in enumerate(phrase_concepts):
        if concepts:
            per_position[index] = concepts
    for index, (word, word_stem) in enumerate(zip(words, stems_)):
        # Stop words inside a phrase add its concept once (at the phrase start), not one unit per word.
        if lex.is_stop(word) and not (per_position[index] and index in anchors):
            continue
        if word.isdigit() and len(word) < 2:
            continue
        result.content.setdefault(word_stem, word)
        result.stem_concepts.setdefault(word_stem, set()).update(per_position[index])
        for concept in per_position[index]:
            result.concepts.setdefault(concept, set()).add(word)
    return result


def describe_query(query: Analysis, lex: Lexicon | None = None) -> dict[str, Any]:
    lex = lex or lexicon()
    return {
        "concepts": [
            {"concept": name, "label": lex.concepts[name].label, "broad": lex.concepts[name].broad,
             "query_words": sorted(words)}
            for name, words in sorted(query.concepts.items())
        ],
        "words_outside_lexicon": sorted(query.content[s] for s, c in query.stem_concepts.items() if not c),
    }


# ---------------------------------------------------------------- scoring


@dataclass
class Match:
    doc_id: str
    score: float
    band: str
    focus: float
    explanation: dict[str, Any]


def score_document(query: Analysis, doc: Analysis, lex: Lexicon | None = None) -> Match | None:
    lex = lex or lexicon()
    if not query.content:
        return None
    total = 0.0
    covered = 0.0
    specific = False
    literal_words: list[str] = []
    uncovered: list[str] = []
    matched_concepts: dict[str, set[str]] = {}
    for word_stem, word in query.content.items():
        concepts = query.stem_concepts.get(word_stem, set())
        weight = lex.token_weight(concepts)
        total += weight
        shared = {name for name in concepts if name in doc.concepts}
        # Lexicon words are compared by sense; only out-of-lexicon words fall back to the same stem.
        literal = not concepts and word_stem in doc.content and not lex.is_stop(word)
        if shared or literal:
            covered += weight
            if literal:
                literal_words.append(word)
                if len(word) >= 4 and not word.isdigit() and not any(lex.concepts[n].broad for n in concepts):
                    specific = True
            for name in shared:
                matched_concepts.setdefault(name, set()).add(word)
                if not lex.concepts[name].broad:
                    specific = True
        else:
            uncovered.append(word)
    if not total or not specific:
        return None
    score = covered / total
    band = "strong" if score >= STRONG else "partial" if score >= PARTIAL else ""
    if not band:
        return None
    focus = len(matched_concepts) / len(doc.concepts) if doc.concepts else 0.0
    explanation = {
        "coverage": round(score, 3),
        "matched_concepts": [
            {"concept": name, "label": lex.concepts[name].label, "query_words": sorted(words),
             "card_words": sorted(doc.concepts[name])}
            for name, words in sorted(matched_concepts.items())
        ],
        "same_word_stems": sorted(set(literal_words)),
        "query_words_not_found": sorted(set(uncovered)),
    }
    return Match("", round(score, 4), band, focus, explanation)


def rank(query_text: str, documents: list[tuple[str, str]], *, limit: int = DEFAULT_LIMIT) -> tuple[Analysis, list[Match]]:
    lex = lexicon()
    query = analyze(query_text, lex)
    matches: list[Match] = []
    for doc_id, text in documents:
        match = score_document(query, analyze(text, lex), lex)
        if match is not None:
            match.doc_id = doc_id
            matches.append(match)
    matches.sort(key=lambda item: (-item.score, -item.focus, item.doc_id))
    return query, matches[:limit]


def validate_query(query: str) -> str:
    if not isinstance(query, str) or not query.strip():
        raise ValueError("запрос пуст")
    if len(query) > MAX_QUERY_CHARS:
        raise ValueError(f"запрос длиннее {MAX_QUERY_CHARS} символов; опишите ситуацию короче")
    return query.strip()


def validate_limit(limit: Any) -> int:
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_LIMIT:
        raise ValueError(f"limit должен быть целым от 1 до {MAX_LIMIT}")
    return limit


def method_card() -> dict[str, Any]:
    lex = lexicon()
    return {
        "method": METHOD,
        "kind": "concept_lexicon_and_stems",
        "embeddings": False,
        "network": False,
        "lexicon": "tools/recall_lexicon.json",
        "lexicon_sha256": lex.digest,
        "concepts": len(lex.concepts),
        "scope": lex.scope,
        "thresholds": {"strong": STRONG, "partial": PARTIAL},
        "false_positive_control": (
            "Показываются только карточки, где покрыта заметная доля слов запроса и есть хотя бы одно "
            "специфичное совпадение; широкие понятия (канал, связь, функция, маркетинг...) сами по себе "
            "результата не дают. Пустой ответ — не доказательство, что опыта не было."
        ),
    }


# ---------------------------------------------------------------- precedents


def precedent_text(item: dict[str, Any]) -> str:
    return "\n".join(str(item.get(key) or "") for key in ("topic", "note", "when"))


def guidance(public: dict[str, Any]) -> str:
    if public.get("retired"):
        return "Отозвано: только история. Не применять; причина отзыва — в retire_reason."
    state = (public.get("source_check") or {}).get("state")
    if state == "unavailable":
        return "Основание сейчас не читается: не использовать как действующее, только как повод спросить."
    if state == "changed":
        return "Основание изменилось после запоминания: откройте источник и перепроверьте до использования."
    if state == "requires_recheck":
        return "Строки совпадают, но основание помечено к пересмотру: сначала перепроверьте."
    return ("Повод проверить переносимость, не факт для этого кейса: назовите одно сходство, одно важное "
            "различие и что подтвердить на данных этого кейса.")


def source_links(public: dict[str, Any]) -> dict[str, str]:
    case = str(public.get("case") or "")
    ref = str(public.get("ref") or "")
    if ref.startswith("D-"):
        registry = f"{case}/decisions/decisions.csv#decision_id={ref}"
    else:
        registry = f"{case}/evidence/conclusions.csv#conclusion_id={ref}"
    return {"source_ref": f"{case}#{ref}", "registry_row": registry, "portfolio_record": f".portfolio/precedents.json#id={public.get('id')}"}


def recall_precedents(root: Path, query: str, *, include_retired: bool = False, limit: int = DEFAULT_LIMIT,
                      selected_case: str | None = None) -> dict[str, Any]:
    query = validate_query(query)
    limit = validate_limit(limit)
    store = precedent.load_store(root)
    items = [item for item in store["items"] if isinstance(item, dict)]
    retired_total = sum(bool(item.get("retired")) for item in items)
    candidates = [item for item in items if include_retired or not item.get("retired")]
    by_id = {str(item.get("id")): item for item in candidates}
    analysis, matches = rank(query, [(str(item.get("id")), precedent_text(item)) for item in candidates], limit=limit)
    checked_at = precedent.utc_now()
    results = []
    for match in matches:
        public = precedent.public_item(by_id[match.doc_id], root, checked_at)
        if public.get("retired"):
            band = "retired_history"
        else:
            band = match.band
        results.append({
            **public,
            "match": {"band": band, "score": match.score, **match.explanation},
            "links": source_links(public),
            "same_case_as_selected": bool(selected_case) and public.get("case") == selected_case,
            "use": guidance(public),
        })
    return {
        "query": query,
        "query_analysis": describe_query(analysis),
        "searched": {"precedents": len(candidates), "retired_excluded": 0 if include_retired else retired_total},
        "items": results,
        "empty_result_means": "Ни одна карточка не прошла порог. Это не доказательство, что такого опыта не было; переформулируйте или смотрите find.",
        "method": method_card(),
        "notice": "Прецедент — память команды о прошлом выборе, не факт и не согласие для этого кейса. Проверка источника сравнивает строки реестров, а не актуальность рынка.",
    }


# ---------------------------------------------------------------- case registries

CASE_REGISTRIES = (
    ("claim", "evidence/claims.csv", "claim_id", ("statement",), ("type", "status", "source_ids", "locator", "period", "unit", "limitations")),
    ("conclusion", "evidence/conclusions.csv", "conclusion_id", ("statement", "change_condition"), ("status", "review_needed", "evidence_ids")),
    ("decision", "decisions/decisions.csv", "decision_id", ("chosen_option", "notes", "revisit_if"), ("decision_kind", "status", "conclusion_ids", "revisit_on")),
    ("commitment", "commitments.csv", "commitment_id", ("description", "review_condition"), ("decision_id", "owner", "status", "due_on")),
)
INACTIVE = {"retracted", "superseded", "cancelled", "rejected"}


def case_documents(case: Path) -> list[dict[str, Any]]:
    documents = []
    for kind, relative, id_field, text_fields, meta_fields in CASE_REGISTRIES:
        try:
            rows = case_scope.read_registry(case, relative, id_field)
        except case_scope.ScopeError as exc:
            if "файл недоступен" in str(exc):
                continue
            raise
        for row in rows:
            documents.append({
                "id": row[id_field],
                "kind": kind,
                "record": f"{relative}#{id_field}={row[id_field]}",
                "text": " ".join(row.get(name, "") for name in text_fields),
                "fields": {name: row.get(name, "") for name in (*text_fields, *meta_fields) if name in row},
                "inactive": (row.get("status") or "").strip().lower() in INACTIVE,
            })
    return documents


def search_case(case: Path, query: str, *, include_inactive: bool = False, limit: int = DEFAULT_LIMIT) -> dict[str, Any]:
    query = validate_query(query)
    limit = validate_limit(limit)
    case_scope.scan_case(case)
    documents = case_documents(case)
    candidates = [doc for doc in documents if include_inactive or not doc["inactive"]]
    by_id = {doc["id"]: doc for doc in candidates}
    analysis, matches = rank(query, [(doc["id"], doc["text"]) for doc in candidates], limit=limit)
    items = []
    for match in matches:
        doc = by_id[match.doc_id]
        items.append({
            "id": doc["id"], "kind": doc["kind"], "record": doc["record"], "fields": doc["fields"],
            "inactive": doc["inactive"], "match": {"band": match.band, "score": match.score, **match.explanation},
        })
    return {
        "query": query,
        "query_analysis": describe_query(analysis),
        "searched": {"rows": len(candidates), "inactive_excluded": 0 if include_inactive else len(documents) - len(candidates)},
        "items": items,
        "method": method_card(),
        "notice": "Найденная строка указывает, где читать. Для решения откройте E-* и фрагмент S-*: совпадение слов не доказывает тезис.",
    }


# ---------------------------------------------------------------- evaluation


def _literal_all(query: str, text: str) -> bool:
    words = [word for word in re.findall(r"[\w-]+", query.casefold()) if word]
    haystack = text.casefold()
    return bool(words) and all(word in haystack for word in words)


def _literal_any_score(query: str, text: str, lex: Lexicon) -> int:
    haystack = text.casefold()
    words = {word for word in re.findall(r"\w+", query.casefold()) if len(word) >= 4 and not lex.is_stop(word)}
    return sum(word in haystack for word in words)


def evaluate(eval_dir: Path) -> dict[str, Any]:
    lex = lexicon()
    cards = json.loads((eval_dir / "precedents.json").read_text(encoding="utf-8"))["items"]
    active = [card for card in cards if not card.get("retired")]
    retired_ids = {card["id"] for card in cards if card.get("retired")}
    report: dict[str, Any] = {"method": method_card(), "sets": {}}
    for query_file in sorted(eval_dir.glob("queries-*.json")):
        payload = json.loads(query_file.read_text(encoding="utf-8"))
        systems: dict[str, dict[str, Any]] = {}
        rows = []
        for system in ("recall", "literal_all_words", "literal_any_word"):
            stats = {"positive": 0, "found_top3": 0, "rr_sum": 0.0, "negatives": 0, "negatives_clean": 0,
                     "queries_with_false_positive": 0, "shown": 0, "false_positive_items": 0,
                     "strong_shown": 0, "strong_wrong": 0, "retired_queries": 0, "retired_found": 0}
            for query in payload["queries"]:
                relevant = set(query.get("relevant", []))
                acceptable = set(query.get("acceptable", []))
                ok = relevant | acceptable
                if system == "recall":
                    _, matches = rank(query["text"], [(c["id"], precedent_text(c)) for c in active], limit=MAX_LIMIT)
                    shown = [m.doc_id for m in matches]
                    strong = [m.doc_id for m in matches if m.band == "strong"]
                elif system == "literal_all_words":
                    shown = [c["id"] for c in active if _literal_all(query["text"], precedent_text(c) + " " + c["id"])]
                    strong = shown
                else:
                    scored = [(c["id"], _literal_any_score(query["text"], precedent_text(c), lex)) for c in active]
                    shown = [cid for cid, s in sorted(scored, key=lambda x: (-x[1], x[0])) if s > 0][:MAX_LIMIT]
                    strong = shown
                wrong = [cid for cid in shown if cid not in ok]
                stats["shown"] += len(shown)
                stats["false_positive_items"] += len(wrong)
                stats["strong_shown"] += len(strong)
                stats["strong_wrong"] += sum(cid not in ok for cid in strong)
                stats["queries_with_false_positive"] += bool(wrong)
                active_relevant = relevant - retired_ids
                if query["kind"] == "positive" and active_relevant:
                    stats["positive"] += 1
                    ranks = [index for index, cid in enumerate(shown, start=1) if cid in active_relevant]
                    if ranks and ranks[0] <= 3:
                        stats["found_top3"] += 1
                    if ranks:
                        stats["rr_sum"] += 1 / ranks[0]
                elif query["kind"] == "positive":
                    stats["retired_queries"] += 1
                    if system == "recall":
                        _, matches = rank(query["text"], [(c["id"], precedent_text(c)) for c in cards], limit=3)
                        stats["retired_found"] += any(m.doc_id in relevant for m in matches)
                    else:
                        stats["retired_found"] += any(_literal_all(query["text"], precedent_text(c)) for c in cards if c["id"] in relevant) if system == "literal_all_words" else any(_literal_any_score(query["text"], precedent_text(c), lex) for c in cards if c["id"] in relevant)
                else:
                    stats["negatives"] += 1
                    stats["negatives_clean"] += not wrong
                if system == "recall":
                    rows.append({"id": query["id"], "kind": query["kind"], "shown": shown, "strong": strong,
                                 "relevant": sorted(relevant), "false_positives": wrong})
            positive = stats["positive"] or 1
            systems[system] = {
                "positive_queries": stats["positive"],
                "recall_at_3": round(stats["found_top3"] / positive, 3),
                "mrr": round(stats["rr_sum"] / positive, 3),
                "negative_queries": stats["negatives"],
                "negative_queries_clean": stats["negatives_clean"],
                "queries_with_false_positive": stats["queries_with_false_positive"],
                "shown_items": stats["shown"],
                "false_positive_items": stats["false_positive_items"],
                "strong_items": stats["strong_shown"],
                "strong_items_wrong": stats["strong_wrong"],
                "retired_only_queries": stats["retired_queries"],
                "retired_found_with_include_retired": stats["retired_found"],
            }
        report["sets"][query_file.stem] = {"provenance": payload.get("provenance"), "queries": len(payload["queries"]),
                                           "systems": systems, "per_query": rows}
    return report


# ---------------------------------------------------------------- CLI


def _print(payload: Any) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=False))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Поиск по смыслу (словарь понятий + основы слов) без сети и моделей.")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("precedents", help="найти прецеденты в .portfolio/ текущей рабочей копии")
    p.add_argument("query")
    p.add_argument("--include-retired", action="store_true")
    p.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    c = sub.add_parser("case", help="найти строки реестров одного кейса")
    c.add_argument("case", help="projects/<slug> или examples/<slug>")
    c.add_argument("query")
    c.add_argument("--include-inactive", action="store_true")
    c.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    a = sub.add_parser("analyze", help="показать понятия, которые словарь видит в запросе")
    a.add_argument("query")
    e = sub.add_parser("eval", help="прогнать набор проверки и сравнить с буквальным поиском")
    e.add_argument("directory")
    e.add_argument("--summary", action="store_true", help="без построчных результатов")
    args = parser.parse_args(argv)
    root = Path.cwd().resolve()
    try:
        if args.command == "precedents":
            _print(recall_precedents(root, args.query, include_retired=args.include_retired, limit=args.limit))
        elif args.command == "case":
            case, _ = case_scope.select_case(root, args.case)
            _print(search_case(case, args.query, include_inactive=args.include_inactive, limit=args.limit))
        elif args.command == "analyze":
            _print({"query": args.query, **describe_query(analyze(validate_query(args.query)))})
        else:
            report = evaluate(Path(args.directory))
            if args.summary:
                for item in report["sets"].values():
                    item.pop("per_query")
            _print(report)
    except (ValueError, OSError, case_scope.ScopeError, precedent.PrecedentError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
