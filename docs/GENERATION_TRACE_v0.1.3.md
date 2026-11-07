# V013-02 — трассировка генерации

Поле `generation_meta` дополняет ответ `POST /generate`, не заменяя
`status`, `card`, `warnings` и `missing_fields`.

## Источники SEO

- `initial_llm` — выбран первый ответ модели.
- `refined_llm` — выбран результат редакторского повтора.
- `llm_grounded` — исходный текст модели безопасно дополнен подтверждёнными характеристиками и повторно проверен.
- `fallback` — выбран локально сформированный текст.
- `none` — SEO-текст не получен.

`llm_attempts` учитывает логические вызовы `generate_text`,
включая неуспешные. Внутренние повторы SDK считаются отдельно
и в это поле не входят.

`reason_codes` фиксирует причины решений генератора:
`insufficient_specs`, `invalid_llm_json`, `seo_too_short`, `seo_too_long`,
`commercial_missing`, `refinement_requested`, `refinement_failed`,
`refinement_rejected`, `refinement_selected`, `refinement_partial`,
`commercial_quarantined`, `seo_grounded_completion`,
`seo_grounded_completion_rejected`, `fallback_unavailable`,
`fallback_rejected`, `fallback_selected`.

Поле `seo_source` отражает выбранное происхождение итогового SEO, а не
показатель редакторского качества. `llm_grounded` не является полностью
исходным текстом модели. Статус `ready_for_review` не подтверждает
достоверность всех смысловых утверждений.

Ни одно поле не содержит ключей GigaChat, промптов, сырых
ответов модели или подробностей исключений.

Исторические JSON без `generation_meta` остаются читаемыми.
Для старых 20 live-карточек источник SEO задним числом
не определяется. Сами исторические результаты не изменяются.

Статус `ready_for_review` по-прежнему требует проверки
редактором и не является разрешением на публикацию.
