# Карточки: инженерия агентной папки

## R-001 — Building effective agents

- Проверено: 17.11.2026, официальный материал Anthropic от 19.12.2024.
- Вопрос: нужен ли собственный runtime/framework или достаточно папки в агентной IDE?
- Что утверждает источник: различает предопределённые workflows и agents, где LLM сама направляет процесс/инструменты; рекомендует начинать с простого решения и учитывать обмен performance на latency/cost. Страница сама отмечает, что часть tooling landscape устарела.
- Ограничение: опыт поставщика, не benchmark нашего кейса; новые managed-agent продукты не меняют формат задания.
- Следствие: среда исполняет цикл, папка даёт durable rules/skills/tools/state; framework не добавляем без измеренной пользы.
- Опровержение решения: fresh consumer не способен автономно выбрать следующий шаг без отдельного runtime или теряет состояние.
- Решение: берём принцип простоты; проверяем consumer и continuation.

## R-007 — Codex AGENTS.md

- Проверено: 17.11.2026, official OpenAI Developers page.
- Вопрос: нужен ли отдельный Codex prompt installer?
- Что утверждает: Codex CLI автоматически перечисляет AGENTS.md от global/root к cwd и вводит их в контекст; более локальные инструкции идут позже.
- Ограничение: не гарантирует конкретную модель, web, цену, квоту или качество следования.
- Следствие: корневой `AGENTS.md` канонический, Codex adapter — документация, не копия prompt.
- Проверка: независимая fresh Codex session должна начать путь с одного consumer prompt.
- Решение: берём.

## R-008 — Cursor Rules

- Проверено: 17.11.2026, official Cursor docs.
- Вопрос: как избежать двух расходящихся prompts?
- Что утверждает: project rules version-controlled; root AGENTS.md поддерживается как простой Markdown alternative. Текущая страница может менять ограничения версий.
- Ограничение: Cursor executable в среде реализации отсутствует; docs read не runtime test.
- Следствие: root AGENTS canonical + tiny alwaysApply pointer, без Cursor-only workflow.
- Проверка: отдельный Cursor consumer прогон.
- Решение: experiment; не заявлять runtime compatibility до прогона.

## R-009 — Spec Kit assess

- Проверено: 17.11.2026, clone exact commit `e210504aa09c9273a38bba665b12b8088468c96f`; README + 5 commands + MIT license.
- Вопрос: принять готовую основу или независимое ядро?
- Что утверждают исходники: intake→research→define→shape→decide; go/needs-clarification/kill; evidence against; user normally runs/reviews each stage; output ends at SDD handoff.
- Ограничение: CLI не установлен; latency/integration not tested. Actual manual adapted mini-run compares process fit only.
- Следствие и решение: [ADR-001](../decisions/foundation-choice.md). Берём идеи gaps/evidence-against/kill, не основу.

