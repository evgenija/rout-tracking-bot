# Route Tracking Bot

Telegram-бот для трекінгу логістичних маршрутів з підтримкою ролей, GPS-геоміток, захисту від РЕБ-спуфінгу та автоматичних звітів.

## Стек

- Python 3.11+
- aiogram 3.7.0
- aiosqlite 0.20.0
- APScheduler 3.10.4
- Хостинг: Railway

## Структура

```
bot/
├── main.py           # точка входу
├── config.py         # white-label налаштування + env
├── handlers/
│   ├── auth.py       # /start, авторизація, /remove
│   ├── tracking.py   # /start_route, /end_route, геолокація
│   └── reports.py    # /report, /weekly
├── models/
│   └── database.py   # SQLite через aiosqlite
└── utils/
    ├── geo.py        # Гаверсин, перевірка спуфінгу
    └── scheduler.py  # APScheduler — щоденний/тижневий звіти
```

## Налаштування

### 1. Клонування та залежності

```bash
git clone <repo>
cd route-tracking-bot
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
```

### 2. Змінні середовища

Скопіюйте `.env.example` у `.env` та заповніть:

```bash
cp .env.example .env
```

| Змінна | Опис |
|---|---|
| `BOT_TOKEN` | Токен від @BotFather |
| `ADMIN_IDS` | Telegram ID адмінів через кому |
| `GROUP_CHAT_ID` | ID групового чату для геоміток |
| `DATABASE_URL` | Залиште порожнім для SQLite |

### 3. Запуск локально

```bash
python -m bot.main
```

### 4. Деплой на Railway

1. Підключіть репозиторій у Railway
2. Додайте змінні середовища через Railway Dashboard
3. Railway автоматично запустить `worker: python -m bot.main` з Procfile

## Ролі

| Роль | Можливості |
|---|---|
| Водій | `/start_route`, `/end_route`, геолокація |
| Адмін | + авторизація водіїв, `/remove`, `/report`, `/weekly` |
| Супер-адмін | + `/finance` (фін. модель, заглушка) |

Адміни задаються через `ADMIN_IDS`. Супер-адміни — через `SUPER_ADMIN_IDS`.

## Команди

### Водій
- `/start` — реєстрація / вітання
- `/start_route` — почати маршрут
- `/end_route` — завершити маршрут (розраховує км)
- Надсилання геолокації + назва точки — фіксація геомітки

### Адмін
- `/remove <telegram_id>` — видалити водія
- `/report` — щоденний звіт
- `/weekly` — тижневий звіт

### Супер-адмін
- `/finance` — фінансова модель (в розробці)

## Автоматичні звіти

- **Щоденний** — щодня о 20:00 (Kyiv) → адмінам в особисті
- **Тижневий** — щонеділі о 20:00 → total по водіях + grand total

## Захист від РЕБ-спуфінгу

Якщо між двома послідовними геомітками відстань > 500 км за < 10 хвилин:
- мітка позначається `⚠️ підозріла`
- адміни отримують сповіщення
- інформація зберігається в БД

## White-label

Назва бота, компанії та вітальне повідомлення редагуються в `bot/config.py`:

```python
BOT_NAME = "Route Tracker Bot"
COMPANY_NAME = "Logistics Co."
WELCOME_MESSAGE = "Ласкаво просимо до системи трекінгу маршрутів {company}!"
```
