# Матрица требований и доказательств

17.11.2026. Статусы — наблюдения, не обещание конкурсного балла. Полный пилот и его ошибки: [pilot/README.md](pilot/README.md).

| Требование | Реализация / доказательство | Граница |
|---|---|---|
| Уточнение и самостоятельный workflow | AGENTS + frame-decision; три fresh consumer-сессии от одного запроса до draft | Синтетические задачи; проверок с людьми нет |
| Документы, таблицы, сайты | PDF/DOCX/CSV/XLSX/HTML через actual ingest; HTTPS example.com и GOV.UK | Статический текст, без OCR/JS; extraction gaps видны |
| Происхождение каждого существенного факта | S/E/C, locators, original/extract hashes; tamper/ID tests | Наличие ссылки не доказывает смысл; legacy locators demo требуют ручной проверки |
| Исследование от решения | research-plan в каждом consumer-кейсе | Fixed-input pilot, не полномасштабное исследование рынка |
| Разные варианты | Четыре варианта; v0.3 требует парного сравнения с ближайшей альтернативой, допущений и switch conditions | Новый pilot-v03 выполнен; raw сохранены, замечания раскрыты |
| Продуктовая и коммуникационная стратегии | strategy.md + promise matrix в трёх кейсах | Рекомендации pending; экономика неизвестна/сценарная |
| План проверки | Метрики/сравнение/срок/guardrails; критика и исправленная методика | Исходные ошибки сохранены; реальные эксперименты не проведены |
| Человек при выборе | human/recommended/simulated различаются; confirmed commitments требуют human decision | Все тестовые решения симулированы либо pending |
| Раздельные знания | instructions/knowledge/case/evidence/state | Не личная память Ouroboros |
| Новый чат | Отдельный cold-сеанс + перенесённая папка с пробелом; v0.3 даёт короткий cold-resume блок | Оба v0.3 cold-run выполнены; та же ОС/модель, другую IDE не доказывает |
| Пересмотр | E-013→E-014, R-001, affected C/D/K; v0.3 требует пересчёта рекомендации, обеих стратегий и memo | v0.3 cold пересчитал, но не сохранил полные прежние тексты; final revise добавил snapshots, проверенные отдельно. D/K не переписываются |
| Прозрачность | runs/operations.csv, отдельный pilot report, модели и known/unknown cost | Часть журнала постфактум; полная модельная стоимость неизвестна |
| Устойчивость | 21 tests: snapshots/recovery/schema/Markdown и плохие входы, pending recovery, late-edit protection, unknown resolution | Single writer; нет полноценного transactional runtime |
| Источники как данные | Вредоносная инструкция в HTML не исполнялась в consumer-отчётах; HTTPS allowlist | Не security sandbox; DNS pinning не реализован |
| Интервью / UX / медиа | Методические ограничения и synthetic labels | Реальных интервью, UX-визуальных анализов, OCR/audio/video input нет |
| Routing / skills / помощники | Шесть skills и выбор процесса/CLI; отдельные критики при разработке | Model routing/MCP/IDE hooks/фон не заявлены |
| Чистый запуск | Python stdlib + Poppler, doctor/tests; отдельная распакованная копия проверяется перед передачей | Linux; Cursor/macOS/Windows не квалифицированы |
| Поставка | Исходники, учебный demo, описание/PDF со снимками, экранный обзор результатов | Официальный бриф, финальное конкурсное видео, публикация и подача не завершены |
