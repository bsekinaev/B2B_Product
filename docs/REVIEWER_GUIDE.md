# Инструкция для проверяющего

**Проект:** B2B Product Content Generator
**Версия:** 0.1.1
**Python:** 3.12

## Назначение

Сервис на FastAPI формирует черновики B2B-карточек
контрольно-измерительных приборов с использованием GigaChat API.

Сервис возвращает SEO-заголовок, SEO-описание, исходные
технические характеристики, поисковые запросы, коммерческий
блок и сведения о проблемах генерации.

Все карточки предназначены для редакторской проверки
перед публикацией.

## Быстрый старт на Windows

Откройте PowerShell в корне репозитория.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

Для выполнения офлайн-тестов ключ GigaChat не требуется.

Для реальной генерации через GigaChat создайте `.env`:

```powershell
Copy-Item .env.example .env
```

Укажите действующие реквизиты `GIGACHAT_CREDENTIALS`
и необходимые параметры доступа из `.env.example`.

**Не добавляйте `.env` в Git.**
Проверка TLS-сертификатов должна оставаться включённой.

Проверка доступности GigaChat при наличии реквизитов:

```powershell
.\.venv\Scripts\python.exe -m scripts.check_gigachat_access
```

## Запуск HTTP-сервиса

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

После запуска:

- `GET http://127.0.0.1:8000/health` — проверка сервиса
- `POST http://127.0.0.1:8000/generate` — генерация карточки
- `http://127.0.0.1:8000/docs` — Swagger UI

Для генерации через API необходим доступ к GigaChat.

## Пример запроса

В новом окне PowerShell, когда API уже запущено:

```powershell
$Body = Get-Content -Raw -Encoding UTF8 `
    "examples/submission/products/rosma_bt_51_211.json"

Invoke-RestMethod `
    -Uri "http://127.0.0.1:8000/generate" `
    -Method Post `
    -Body $Body `
    -ContentType "application/json; charset=utf-8"
```

Второй входной пример:

`examples/submission/products/meter_dm02_series.json`

Сохранённые результаты:

- `examples/submission/results/rosma_bt_51_211.json`
- `examples/submission/results/meter_dm02_series.json`

Эти JSON-результаты демонстрируют проверенный офлайн-fallback.
Они не являются доказательством того, что новая генерация
GigaChat выдаст побуквенно такой же текст.

Способ подготовки примеров описан в
`examples/submission/provenance.json`.

## Тестирование без GigaChat

```powershell
.\.venv\Scripts\python.exe -m pytest -q --cov=app --cov-branch --cov-report=term-missing
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -m scripts.run_acceptance
```

Дополнительные 24 синтетических сценария:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_synthetic_batch.py
.\.venv\Scripts\python.exe -m scripts.run_synthetic_batch --output artifacts/reviewer_batch
```

Папка `artifacts/reviewer_batch` не должна существовать до
запуска. Для повторного запуска выберите другое имя папки.

Проверенный результат опубликованной версии v0.1.1:
**280 тестов PASS, покрытие с ветвлениями 96%**.
Тестирование проводилось на Windows и Python 3.12.3.

## Статусы генерации

`ready_for_review` — формальная проверка пройдена,
но карточка ещё требует редакторского одобрения.

`requires_revision` — требуется доработка, например
при неподтверждённых утверждениях или несоблюдении ограничений.

`insufficient_data` — исходных сведений недостаточно
для содержательной генерации.

Отрицательный сценарий считается успешным тестом,
когда сервис корректно выявляет проблему.

## Основные компоненты

- `app/main.py` — HTTP API
- `app/schemas.py` — структуры входных и выходных данных
- `app/llm/client.py` — взаимодействие с GigaChat
- `app/llm/prompts.py` — правила формирования LLM-ответа
- `app/generator.py` — сборка и проверка результата
- `app/validation.py` — формальные и защитные проверки
- `app/grounded_copy.py` — проверяемый SEO-fallback
- `app/grounded_commercial.py` — коммерческий блок из исходных фактов

Исходные характеристики не передаются модели для изменения:
в итоговой структуре они копируются из входного JSON.

## Известные ограничения

Качество смысла и стилистики не гарантируется
формальной валидацией; нужна редакторская проверка.

Для товара с вариантами серии необходимо отдельно выбрать
конкретное исполнение. Это требование отражается в тексте,
но `missing_fields` не служит полным конфигуратором изделия.

Результаты 24 синтетических испытаний получены
с подменённым LLM-провайдером. Это не 24 сетевых вызова GigaChat.

Отдельные проверки не доказывают промышленную готовность,
доступность сервиса под нагрузкой или корректность всех
будущих ответов языковой модели.

## Дополнительные материалы

- `docs/ACCEPTANCE.md` — отчёт приёмки
- `docs/ACCEPTANCE_HISTORY_v0.1.0.md` — предыдущий отчёт
- `docs/RELEASE_NOTES_v0.1.1.md` — изменения релиза
- `examples/submission/provenance.json` — происхождение примеров
- `examples/submission/synthetic_summary.json` — сводка 24 испытаний
