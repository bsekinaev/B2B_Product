# Архитектурный план генератора B2B-карточек товаров

**ADR-001:** развивать модульный монолит на Python/FastAPI.

Микросервисы не вводить без доказанной необходимости.

> **Статус документа:** целевая архитектура и дорожная карта будущих версий, а не описание уже реализованной v0.1.3. В текущей версии работает локальный FastAPI-сервис без PostgreSQL, фоновых очередей и CMS-интеграции. Реализованные возможности и ограничения см. в [приёмке v0.1.3](ACCEPTANCE_v0.1.3.md).

## 1. Целевая архитектура

Импорт данных
→ нормализация характеристик
→ каталог PostgreSQL
→ фоновая генерация
→ GigaChat / fallback
→ проверка фактов
→ редакторская проверка
→ экспорт.

Генерация текста отделена от хранения исходных фактов.

## 2. Основные модули

### catalog

Товары, производители, категории, артикулы,
варианты исполнения.

### specifications

Определения характеристик, типы значений,
единицы измерения, проверка обязательных полей.

### generation

Промпты, адаптер LLM, повторные попытки,
fallback, версии генераций.

### evidence

Исходные документы, ссылки на производителя,
подтверждение конкретных утверждений.

### quality

Формальная валидация, проверка соответствия фактам,
набор оценочных примеров.

### editorial

Очередь редакторской проверки, исправления,
утверждение и история изменений.

### integration

Импорт CSV/Excel, JSON API, экспорт
для систем управления каталогом.

### telemetry

Время обработки, ошибки, токены, стоимость
и процент карточек, требующих доработки.

## 3. Предметная модель v0.2.0

### product_categories

id UUID PK
code TEXT UNIQUE
name_ru TEXT
schema_version INTEGER

Определяет семейство оборудования
и требования к его характеристикам.

### attribute_definitions

id UUID PK
category_id UUID FK
code TEXT
name_ru TEXT
data_type TEXT
unit_code TEXT NULL
required_for_selection BOOLEAN
validation_rules JSONB

Уникальность: category_id + code.

### products

id UUID PK
manufacturer TEXT
source_sku TEXT NULL
name TEXT
category_id UUID FK
description TEXT NULL
created_at TIMESTAMP
updated_at TIMESTAMP

Артикул и производитель используются
для определения идентичности товара.

### product_variants

id UUID PK
product_id UUID FK
variant_sku TEXT NULL
variant_name TEXT
configuration_state TEXT

Позволяет отделить серию приборов
от конкретного исполнения.

### attribute_values

id UUID PK
product_id UUID NULL
variant_id UUID NULL
definition_id UUID FK
raw_value TEXT
normalized_value JSONB NULL
unit_code TEXT NULL
source_id UUID NULL

Raw-значение хранить без потери исходных данных.

Значение должно принадлежать либо продукту,
либо варианту исполнения.

### sources

id UUID PK
source_kind TEXT
uri TEXT NULL
document_hash TEXT NULL
title TEXT
captured_at TIMESTAMP

Источники должны быть проверяемыми.

### generation_jobs

id UUID PK
product_id UUID FK
variant_id UUID NULL
idempotency_key TEXT
status TEXT
attempts INTEGER
model_id TEXT
prompt_version TEXT
input_hash TEXT
last_error_code TEXT NULL

Идемпотентность предотвращает дублирование
результата при повторном выполнении задачи.

### card_revisions

id UUID PK
product_id UUID FK
variant_id UUID NULL
generation_job_id UUID NULL
revision INTEGER
payload JSONB
editorial_status TEXT
created_by TEXT
approved_by TEXT NULL
created_at TIMESTAMP

Редактирование создаёт новую ревизию.
Утверждённый снимок не изменяется задним числом.

### claim_evidence

id UUID PK
card_revision_id UUID FK
claim_text TEXT
source_id UUID NULL
attribute_value_id UUID NULL
verdict TEXT
explanation TEXT

Допустимые verdict:

- supported
- unsupported
- unknown

Простое совпадение числа с исходными данными
не считается достаточным доказательством.

### review_events

id UUID PK
card_revision_id UUID FK
actor_id TEXT
action TEXT
comment TEXT
created_at TIMESTAMP

Нужен для аудита редакторских решений.

## 4. Принципы проектирования БД

PostgreSQL является источником истины.

JSONB используется для гибких снимков и правил,
но не заменяет ключевые реляционные связи.

Управление схемой — Alembic.

Нужны индексы по категориям, товарам,
статусам заданий и ревизиям карточек.

## 5. Пакетная генерация v0.3.0

Celery отвечает за выполнение заданий.
Redis используется как брокер.

PostgreSQL хранит устойчивое состояние заданий.

Повторные попытки выполняются только
для временных ошибок.

Каждая задача должна иметь:

- идентификатор;
- ограничение попыток;
- таймаут;
- ключ идемпотентности;
- диагностический статус.

Ограничить параллельные обращения к GigaChat.

Не передавать секреты в payload очереди.

## 6. Редакторский процесс v0.4.0

Предлагаемые роли:

- admin;
- editor;
- viewer.

Жизненный цикл карточки:

draft → in_review → approved

Также возможны:

- rejected;
- needs_changes.

Изменение утверждённой карточки создаёт
новую ревизию, требующую проверки.

Экспорт доступен только для утверждённых версий.

## 7. LLMOps v0.5.0

Для каждой генерации измерять:

- модель;
- версию промпта;
- длительность;
- количество токенов;
- стоимость, если рассчитывается;
- использование fallback;
- ошибки;
- итог проверки качества.

Основные показатели:

- доля успешных черновиков с первого раза;
- доля fallback;
- процент редакторских исправлений;
- средняя стоимость карточки;
- p50/p95 времени генерации.

Качество оценивать на размеченном наборе товаров,
а не только через unit-тесты.

## 8. Безопасность публичной версии

Перед внешним развёртыванием необходимы:

- аутентификация;
- разграничение прав;
- rate limiting;
- квоты;
- безопасная обработка загрузок;
- защита от CSV formula injection;
- ограничение внешних URL;
- безопасное логирование;
- управление секретами.

## 9. Демонстрация для портфолио

Целевой сценарий:

1. Импортировать 20 синтетических товаров.
2. Запустить массовую генерацию.
3. Просмотреть результаты и предупреждения.
4. Исправить неподтверждённые утверждения.
5. Утвердить выбранные карточки.
6. Экспортировать их в CSV/JSON.

Не заявлять промышленное использование,
если такое внедрение не подтверждено.

## 10. Управление сложностью

v0.1.2 — исправление MVP и CI.
v0.2.0 — предметная модель и БД.
v0.3.0 — массовая обработка.
v0.4.0 — редакторский процесс.
v0.5.0 — эксплуатация и LLMOps.

Каждая версия должна быть самостоятельно проверяемой.
