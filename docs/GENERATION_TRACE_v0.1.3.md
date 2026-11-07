# V013-02 — трассировка генерации

Поле `generation_meta` дополняет ответ `POST /generate`, не заменяя
`status`, `card`, `warnings` и `missing_fields`.

## Источники SEO

- `initial_llm` — выбран первый ответ модели.
- `refined_llm` — выбран результат редакторского повтора.
- `fallback` — выбран локально сформированный текст.
- `none` — SEO-текст не получен.

`llm_attempts` учитывает логические вызовы `generate_text`,
включая неуспешные. Внутренние повторы SDK считаются отдельно
и в это поле не входят.

`reason_codes` фиксирует причины решений генератора:
`insufficient_specs`, `invalid_llm_json`, `seo_too_short`,
`commercial_missing`, `refinement_requested`, `refinement_failed`,
`refinement_rejected`, `refinement_selected`,
`fallback_unavailable`, `fallback_rejected`, `fallback_selected`.

Ни одно поле не содержит ключей GigaChat, промптов, сырых
ответов модели или подробностей исключений.

Исторические JSON без `generation_meta` остаются читаемыми.
Для старых 20 live-карточек источник SEO задним числом
не определяется. Сами исторические результаты не изменяются.

Статус `ready_for_review` по-прежнему требует проверки
редактором и не является разрешением на публикацию.
