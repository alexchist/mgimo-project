# Детализация журнала: PromptBench-RU v1

Источник: [120 ответов и методика](README.md). Для коротких задач ниже все пары с изменением хотя бы одного строго оценённого поля. Пропущенные пары совпали по всем отметкам, не обязательно по тексту. Изменение имени ключа может изменить балл, не смысл. Для записок — все пары и обе слепые оценки, биты соответствуют порядку [пяти требований своей задачи](../../evals/promptbench/rubric.md). 1 на позиции означает зачтённое требование. Риск указан отдельно (1 = отмечен). Не суммировать как независимые подтверждения.

|Модель|Задача, повтор|Ответ A → B|Стало верно|Перестало быть верно|
|---|---|---|---|---|
|GigaChat-3-Lightning|01, 1|[039](runs/039.json) → [040](runs/040.json)|—|work_days|
|GigaChat-3-Lightning|01, 2|[102](runs/102.json) → [101](runs/101.json)|—|work_days|
|GigaChat-3-Lightning|02, 2|[115](runs/115.json) → [116](runs/116.json)|overall_direction|—|
|GigaChat-3-Pro|03, 2|[087](runs/087.json) → [088](runs/088.json)|—|n_b|
|GigaChat-3-Pro|04, 1|[015](runs/015.json) → [016](runs/016.json)|—|prepaid_now|
|GigaChat-3-Pro|04, 2|[108](runs/108.json) → [107](runs/107.json)|stores|—|
|GigaChat-3-Pro|05, 2|[062](runs/062.json) → [061](runs/061.json)|—|first_step|
|GigaChat-3-Pro|07, 1|[011](runs/011.json) → [012](runs/012.json)|—|mature_pct|
|GigaChat-3-Pro|07, 2|[094](runs/094.json) → [093](runs/093.json)|—|mature_pct|
|GigaChat-3-Ultra|02, 2|[066](runs/066.json) → [065](runs/065.json)|within_direction|—|
|GigaChat-3-Ultra|03, 1|[025](runs/025.json) → [026](runs/026.json)|—|paid_delta_pp, complaints_delta_pp|
|GigaChat-3-Ultra|03, 2|[064](runs/064.json) → [063](runs/063.json)|—|paid_delta_pp|
|GigaChat-3-Ultra|07, 1|[057](runs/057.json) → [058](runs/058.json)|earliest_full_day|—|

|Модель|Кейс, повтор|Ответ A → B|Читатель 1: отметки; риск|Читатель 2: отметки; риск|
|---|---|---|---|---|
|GigaChat-3-Lightning|09, 1|[020](runs/020.json) → [019](runs/019.json)|`00000` → `00000`; 1 → 1|`00000` → `00000`; 1 → 1|
|GigaChat-3-Lightning|09, 2|[117](runs/117.json) → [118](runs/118.json)|`00000` → `00000`; 1 → 1|`00100` → `00000`; 1 → 1|
|GigaChat-3-Lightning|10, 1|[045](runs/045.json) → [046](runs/046.json)|`01001` → `00010`; 1 → 0|`01001` → `01010`; 1 → 0|
|GigaChat-3-Lightning|10, 2|[096](runs/096.json) → [095](runs/095.json)|`01000` → `01010`; 0 → 0|`00000` → `01010`; 0 → 0|
|GigaChat-3-Pro|09, 1|[038](runs/038.json) → [037](runs/037.json)|`00100` → `00000`; 1 → 1|`00100` → `00110`; 1 → 0|
|GigaChat-3-Pro|09, 2|[091](runs/091.json) → [092](runs/092.json)|`00100` → `10110`; 1 → 0|`00100` → `10110`; 1 → 0|
|GigaChat-3-Pro|10, 1|[030](runs/030.json) → [029](runs/029.json)|`01011` → `01001`; 0 → 1|`01011` → `01001`; 0 → 1|
|GigaChat-3-Pro|10, 2|[105](runs/105.json) → [106](runs/106.json)|`01010` → `01010`; 1 → 0|`01000` → `01010`; 1 → 0|
|GigaChat-3-Ultra|09, 1|[056](runs/056.json) → [055](runs/055.json)|`00000` → `11010`; 1 → 0|`01000` → `11110`; 1 → 0|
|GigaChat-3-Ultra|09, 2|[071](runs/071.json) → [072](runs/072.json)|`10010` → `11000`; 1 → 0|`10010` → `11000`; 0 → 0|
|GigaChat-3-Ultra|10, 1|[060](runs/060.json) → [059](runs/059.json)|`10010` → `01010`; 1 → 0|`11110` → `11110`; 0 → 0|
|GigaChat-3-Ultra|10, 2|[067](runs/067.json) → [068](runs/068.json)|`01011` → `01011`; 0 → 0|`11111` → `11111`; 0 → 0|
