# MCP: Стратег только на чтение

Локальный stdio-сервер [`tools/strategist_mcp.py`](../../tools/strategist_mcp.py) даёт агенту четыре инструмента: поиск прецедентов по смыслу, `resume`, `check` и поиск по реестрам выбранного кейса. Сервер ничего не пишет, не принимает путей и команд. Нужен только Python 3 (проверено на 3.12), без пакетов.

Полная инструкция, границы и результаты проверки: [docs/mcp-recall/README.md](../../docs/mcp-recall/README.md).

## Cursor (подключается вручную)

В репозитории нет `.cursor/mcp.json`, поэтому сервер не включится сам. Чтобы подключить:

1. Если `.cursor/mcp.json` ещё нет, скопируйте туда [`cursor-mcp.example.json`](cursor-mcp.example.json). Если файл уже есть, добавьте только запись `strategist` в его `mcpServers`, не заменяя остальные настройки.
2. Замените `projects/your-case` на свой кейс (`projects/<slug>` или `examples/demo`). Без `--case` и его значения будет доступен только `precedent_recall`.
3. В Windows вместо `python3` обычно пишут `python`.
4. Включите сервер в Cursor → Customize → MCP. По умолчанию Cursor спрашивает разрешение перед каждым вызовом инструмента.

Формат и переменная `${workspaceFolder}` сверены с [документацией Cursor](https://cursor.com/docs/context/mcp) 20.11.2026. Сам Cursor с этим конфигом не запускался: в среде сборки не было рабочего Cursor. Проверка клиентом — через официальный Python SDK, см. ниже.

## Другие клиенты

Любой MCP-клиент со stdio запускает ту же команду из корня рабочей копии:

```sh
python3 tools/strategist_mcp.py --case projects/<slug>
```

Проверены только официальный Python SDK `mcp==2.3.0` и встроенный в тесты JSON-RPC-клиент. Другие клиенты не запускались.

## Файлы

| Файл | Назначение |
|---|---|
| `cursor-mcp.example.json` | пример для `.cursor/mcp.json`; сам не включается |
| `demo_workspace.py` | временная рабочая копия: копия `examples/demo` и выделенные карточки, записанные реальным `precedent.py remember/retire` |
| `sdk_roundtrip.py` | официальный SDK-клиент → сервер; сохраняет протокол, при несовпадении ожиданий завершается с кодом 1 |
