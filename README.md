
# B2B Product Content Generator

Сервис подготовки B2B-карточек контрольно-измерительных приборов
с использованием GigaChat API.

Разрабатывается в рамках технического задания компании «СОЮЗ-ПРИБОР».

## Быстрый старт

Требуется Python 3.12.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

Документация API: http://127.0.0.1:8000/docs

## Конфигурация

```powershell
Copy-Item .env.example .env
```

Укажите Authorization key GigaChat в `GIGACHAT_CREDENTIALS`.

При необходимости настройте доверенный сертификат через
`GIGACHAT_CA_BUNDLE_FILE`. Проверка TLS обязательна.

Проверка подключения:

```powershell
.\.venv\Scripts\python.exe -m scripts.check_gigachat_access
```

Секреты и локальные сертификаты исключены из Git.

## Проверки

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
```

## API

`GET /health` — проверка работоспособности приложения.

```json
{"status": "ok"}
```

Генерация карточек пока не реализована.

## Модели данных

`app/schemas.py` содержит `ProductInput`, `ProductCard`, `GenerationResult`
и три допустимых значения `GenerationStatus`.

Входные поля: `name`, `manufacturer`, `specs`, `description`.
Обязательные строки проверяются, пробелы удаляются без изменения
числовых значений и единиц измерения. Совпадающие после удаления
пробелов названия характеристик отклоняются. Лимит нормализованных
данных товара — 16 КиБ (не размер исходного HTTP-запроса).

Проверки SEO-текста и маршрут `POST /generate` будут добавлены позднее.

## GigaChat Provider

`app/llm/client.py` изолирует вызов SDK, проверяет наличие ключа и
доверенного CA-файла, отклоняет неполные ответы модели и возвращает
текст или безопасный код ошибки.
Повторы сетевых запросов выполняет только SDK (`GIGACHAT_MAX_RETRIES`).
Ручной smoke-тест текстовой генерации (реальный запрос к API):

```powershell
.\.venv\Scripts\python.exe -m scripts.check_gigachat_completion
```
