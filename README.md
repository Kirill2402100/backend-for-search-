# dental-leads backend

Назначение:
- собираем лиды стоматологий США по штатам
- обогащаем email
- валидируем email
- шлём холодные письма
- трекаем ответы
- управляем всем через Telegram

Стек:
- FastAPI (Python)
- ClickUp API как CRM
- SMTP для отправки писем
- Telegram bot для команд `/send` и `/status`

Основные эндпоинты (MVP):
- `POST /lead/bulk-import` — импорт лидов из Google Places / Yelp / Zocdoc
- `POST /lead/from-fb` — сохранить лид из расширения браузера (добавить email)
- `POST /send` — отправить N писем по штату
- `GET /status` — статистика по штату
