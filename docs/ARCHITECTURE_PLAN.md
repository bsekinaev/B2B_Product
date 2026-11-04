# Архитектура и дорожная карта B2B Product Content Generator

**ADR-001.** Развивать модульный монолит на FastAPI, а не набор микросервисов. Текущая v0.1.2 исправляет качество без БД и брокера. Будущая платформа управляет импортом, исходными характеристиками, происхождением фактов, генерациями и редакторским циклом.

## 1. Поток данных

Импорт JSON/CSV/Excel → проверка схемы → категория и нормализация характеристик → PostgreSQL → generation job → GigaChat или deterministic fallback → независимая валидация → evidence/quality checks → human review → экспорт утверждённого результата.

Модель не переписывает структурированные факты и не имеет полномочия утверждать карточку.

## 2. Модули
- api: HTTP API, DTO, унифицированные ошибки, авторизация, лимиты.
- catalog: производитель, товар, категория, артикула и варианты исполнения.
- specs: технические определения, исходное raw_value и проверяемая нормализация единиц.
- evidence: ссылки на документы и подтверждения утверждений.
- generation: provider adapters, versioned prompts, fallback, генерационные задания.
- quality: формальные правила, claim validation, evaluation dataset и quality reports.
- editorial: ревизии, решения редакторов и журнал изменений.
- import_export: CSV/Excel/JSON, проверка источников, экспорт в CMS.
- telemetry: latency, cost/tokens, retry rate, предупреждения и статистика качества.

Для v0.1.2 не переносить существующие файлы по этим модулям без необходимости. Рефакторинг только после фиксации поведения тестами.

## 3. Предметная модель v0.2.0

### product_categories
id UUID PK, code TEXT UNIQUE, name_ru TEXT, schema_version INT, created_at. Для каждой категории свой набор обязательных атрибутов; требования для манометра и термометра не смешивать.

### attribute_definitions
id UUID PK, category_id FK, code TEXT, name_ru TEXT, value_type (text/decimal/range/enum), unit_code nullable, required_for_selection BOOL, validation_rules JSONB. UNIQUE(category_id, code). Схемы имеют версии.

### products
id UUID PK, manufacturer TEXT, source_sku nullable, category_id FK, name TEXT, description TEXT nullable, source_state TEXT, timestamps. При наличии артикула индекс уникальности по нормализованному производителю и source_sku; название не обязано быть уникальным.

### product_variants
id UUID PK, product_id FK, variant_sku nullable, name TEXT, configuration_state (unknown/partial/complete), timestamps. Несколько вариантов серии не превращаются в одну комбинацию параметров.

### attribute_values
id UUID PK, product_id FK nullable, variant_id FK nullable, attribute_definition_id FK, raw_value TEXT, normalized_value JSONB nullable, unit_code nullable, source_id FK nullable, captured_at. CHECK: привязка к product или variant — ровно одна. При изменении нормализации raw_value не теряется. Свойства корпуса не переносить на гильзу.

### sources
id UUID PK, kind (manufacturer_catalog/datasheet/operator/import), uri nullable, document_hash nullable, title, captured_at, provenance_note. Хранить неизменяемые ссылки на данные и иметь политику хранения документов; осторожно с лицензией производителя и пользовательскими загрузками.

### generation_jobs
id UUID PK, product_id FK, variant_id FK nullable, idempotency_key TEXT, status (queued/running/succeeded/requires_revision/failed), attempts INT, model_id TEXT, prompt_version TEXT, input_hash TEXT, last_error_code nullable, created_at, started_at, finished_at. Ключ идемпотентности определять с учётом владельца/пользователя. Повтор не должен создавать дубликаты карточек.

### card_revisions
id UUID PK, product_id FK, variant_id FK nullable, job_id FK nullable, revision INT, payload JSONB, editorial_status (draft/in_review/approved/rejected), created_by, approved_by nullable, created_at, approved_at nullable. Уникальность ревизии гарантируется для отдельного товара/варианта. Редактирование создаёт новую immutable revision.

### claim_evidence
id UUID PK, card_revision_id FK, claim_text TEXT, attribute_value_id FK nullable, source_id FK nullable, check_kind TEXT, verdict (supported/unsupported/unknown), explanation TEXT, created_at. Совпадение числа с любым входным числом не подтверждает claim.

### review_events
id UUID PK, card_revision_id FK, actor_id, action (submit/approve/reject/request_changes), comment, created_at. Сохранять аудит решения и запрещать несогласованные переходы состояний.

Рекомендуемые индексы: products(category_id, manufacturer), product_variants(product_id), generation_jobs(status, created_at), card_revisions(product_id, created_at DESC), claim_evidence(card_revision_id, verdict). Выполнять через Alembic, не хранить всё предметное состояние в одной JSONB колонке.

## 4. Очереди и batch processing v0.3.0

Redis — брокер, PostgreSQL — источник устойчивого состояния. Celery-обработчики получают только job_id; секреты и полный текст в очередь не класть. Retry исключительно для временных ошибок, с backoff, jitter и верхним пределом попыток; недостоверный LLM-ответ не повторять бесконечно. Защита от повторной обработки — idempotency_key и атомарная запись результата.

Границы нагрузки измерять, а не угадывать: concurrency limit на провайдера, ограничения пакета, таймауты, квоты и компенсация прерванных задач. Индикаторы: p50/p95 latency, доля provider failure, retries, fallback_used, оценка расхода токенов на карточку.

## 5. Human-in-the-loop v0.4.0

Роли admin, editor, viewer. Основной путь: draft → in_review → approved / rejected / needs_changes. Изменение approved создаёт новую ревизию, которая не считается утверждённой. Редактор видит source values и ссылки на evidence рядом с каждым заявлением. Экспорт в CMS запрещён для requires_revision, draft и unknown claims без отдельного решения.

Не строить большой SPA, пока DTO, ревизии и роли не зафиксированы; начать с небольшого служебного интерфейса.

## 6. LLMOps и эксплуатация v0.5.0

Версионировать системные промпты, модель, generation schema и правила проверки. В job metadata: provider, model, prompt_version, latency, tokens_in/out если SDK их сообщает, fallback_used, validation warnings, status и ошибки в безопасном виде. На вручную размеченном evaluation dataset измерять factual consistency, приёмку с первого раза и долю исправлений редактором. Это независимая ось качества, отличная от unit coverage.

Для публикации API во внешнюю сеть нужны: аутентификация, RBAC, per-user quota, rate limiting, защищённые uploads, защита от CSV formula injection при экспорте, ограничение обращений к внешним URL, секреты в менеджере окружения, структурированные логи и аудит. RAG возможен лишь с контролируемыми источниками и тестами prompt injection.

## 7. Ограничение объёма и портфолио

v0.1.2 — устранение дефектов и зелёный CI. v0.2 — схема БД и доказательства происхождения. v0.3 — batch и отказоустойчивость. v0.4 — редакторский процесс. v0.5 — эксплуатация и метрики.

Демо для портфолио: импорт 20 синтетических приборов, очередь, черновики, ошибки фактов, исправление/approve, экспорт только утверждённых карточек. Показывать честные метрики и ссылаться на исходное ТЗ как на источник задачи, не как на свидетельство промышленного внедрения.
