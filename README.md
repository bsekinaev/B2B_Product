
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

`POST /generate` принимает JSON товара и возвращает структурированный черновик.

## Модели данных

`app/schemas.py` содержит `ProductInput`, `ProductCard`, `GenerationResult`
и три допустимых значения `GenerationStatus`.

Входные поля: `name`, `manufacturer`, `specs`, `description`.
Обязательные строки проверяются, пробелы удаляются без изменения
числовых значений и единиц измерения. Совпадающие после удаления
пробелов названия характеристик отклоняются. Лимит нормализованных
данных товара — 16 КиБ (не размер исходного HTTP-запроса).

Повторяющиеся ключи исходного JSON отклоняются; сырое HTTP-тело — до 32 КиБ.
До независимой проверки SEO и достоверности результат получает статус
`requires_revision`, а при отсутствии фактов — `insufficient_data`.
Статус `ready_for_review` появится после реализации проверок на этапе 5.

## GigaChat Provider

`app/llm/client.py` изолирует вызов SDK, проверяет наличие ключа и
доверенного CA-файла, отклоняет неполные ответы модели и возвращает
текст или безопасный код ошибки.
Повторы сетевых запросов выполняет только SDK (`GIGACHAT_MAX_RETRIES`).
Ручной smoke-тест текстовой генерации (реальный запрос к API):

```powershell
.\.venv\Scripts\python.exe -m scripts.check_gigachat_completion
```

## Генерация через API

В Swagger (`/docs`) доступен `POST /generate`. Пример запроса:

```json
{
  "name": "Манометр показывающий DM 02",
  "manufacturer": "Манотомь",
  "specs": {
    "диапазон измерений": "0–1,6 МПа",
    "класс точности": "1,5"
  },
  "description": "Прибор предназначен для измерения избыточного давления."
}
```

SEO- и коммерческие тексты составляет GigaChat в строго заданной JSON-структуре;
технические характеристики переносятся только из исходных данных.
Проверки нормативной длины SEO и достоверности текстовых утверждений — этап 5.
При ошибке провайдера API возвращает безопасный код без текста запроса и секретов.

Прототип предназначен для локального запуска (`127.0.0.1`). Маршрут
`POST /generate` пока не имеет пользовательской авторизации; не открывайте
его в интернет без контроля доступа и частоты запросов.
