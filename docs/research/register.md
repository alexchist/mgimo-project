# Реестр research

Дата среза: 17.11.2026. `verified-this-run` означает, что автор реализации открыл первоисточник в этой сессии. `reported-in-master-plan` означает, что вывод перенесён из принятого мастер-плана и не выдаётся за повторную проверку. Открытая страница не доказывает доступ аккаунта, цену или качество продукта.

| ID | Источник | Статус чтения | Использование |
|---|---|---|---|
| R-001 | [Anthropic: Building effective agents](https://www.anthropic.com/research/building-effective-agents), 19.12.2024 | verified-this-run; страница предупреждает, что landscape изменился | простое composable ядро, agent vs workflow, complexity trade-off |
| R-002 | Anthropic: Effective context engineering for AI agents | reported-in-master-plan | checkpoint, progressive disclosure; не независимая текущая проверка |
| R-003 | Anthropic: Writing effective tools for agents—with agents | reported-in-master-plan | ясные ошибки и realistic evals |
| R-004 | Anthropic: multi-agent research system | reported-in-master-plan | помощники только для независимых вопросов |
| R-005 | Anthropic: Agent Skills | reported-in-master-plan | skill как папка; actual cross-IDE behavior не доказано |
| R-006 | Anthropic: long-running agent harnesses | reported-in-master-plan | start/resume и checkpoint |
| R-007 | [OpenAI: Codex prompting guide, Using agents.md](https://developers.openai.com/cookbook/examples/gpt-5/codex_prompting_guide#using-agentsmd) | verified-this-run | Codex CLI подбирает AGENTS.md root→cwd |
| R-008 | [Cursor: Rules](https://cursor.com/docs/context/rules) | verified-this-run docs; runtime unavailable | root AGENTS.md and thin `.cursor/rules` |
| R-009 | [GitHub Spec Kit assess README](https://github.com/github/spec-kit/tree/e210504aa09c9273a38bba665b12b8088468c96f/extensions/assess) | verified-this-run at exact commit | actual five-stage comparison, evidence against, honest kill |
| R-010 | OpenAI Deep Research help | reported-in-master-plan | external baseline candidate; not installed/tested |
| R-011 | Perplexity Research | reported-in-master-plan | external baseline candidate; not installed/tested |
| R-012 | Dovetail, Productboard, EnjoyHQ official product/pricing/help pages | reported-in-master-plan | research repository / feedback→decision patterns; no hands-on |
| R-013 | GPT Researcher docs; STORM repository/paper | reported-in-master-plan | research-oriented analogs; not installed/tested |
| R-014 | BMAD method | reported-in-master-plan | role/template analog; not installed/tested |
| R-015 | MarkItDown and Docling repositories | reported-in-master-plan | import candidates; not chosen due dependency/precision trade-off |
| R-016 | [Christensen Institute: What is JTBD](https://www.christenseninstitute.org/video/what-is-jobs-to-be-done-theory/) | verified-this-run | circumstances + progress, not demographic label |
| R-017 | [April Dunford: positioning quickstart](https://www.aprildunford.com/post/a-quickstart-guide-to-positioning) | verified-this-run | alternatives→capabilities→value→audience→category |
| R-018 | [Strategyzer: value proposition](https://www.strategyzer.com/value-proposition) | verified-this-run | few important jobs/pains/gains and real-world tests |
| R-019 | [Safe Velocity at Scale, ICSE-SEIP 2019](https://exp-platform.com/Documents/2019%20TongXiaSumitBhardwajPavelDmitrievAleksanderFabijan_Safe-Velocity-ICSE-SEI.pdf) | verified-this-run landing/PDF extract | data-quality, success and guardrail metric roles |
| R-020 | [MGIMO AI Challenge site](https://challenge.mgimo.ai/) and [rules](https://challenge.mgimo.ai/rules), edition 22.10.2026 | verified-this-run | deadline/results/submission/IP caveat; no permission to submit |

Ранее сообщённые Anthropic/analogs rows сохранены для трассировки мастер-плана. До цитирования их конкретного тезиса в конкурсном описании страницу нужно открыть заново и записать дату/версию.

