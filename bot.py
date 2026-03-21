import json
import os
from datetime import datetime

from dotenv import load_dotenv
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from route import calculate_total_distance_km

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_IDS = os.getenv("ADMIN_IDS", "")
GROUP_CHAT_ID = os.getenv("GROUP_CHAT_ID")
TEST_MODE_ALLOW_ZERO_DISTANCE = os.getenv("TEST_MODE_ALLOW_ZERO_DISTANCE", "false").lower() == "true"

if ADMIN_IDS:
    ADMIN_IDS = [int(x.strip()) for x in ADMIN_IDS.split(",") if x.strip()]
else:
    ADMIN_IDS = []

if GROUP_CHAT_ID:
    GROUP_CHAT_ID = int(GROUP_CHAT_ID)

DATA_DIR = os.getenv("DATA_DIR") or os.getenv("RAILWAY_VOLUME_MOUNT_PATH") or "."
os.makedirs(DATA_DIR, exist_ok=True)

DRIVERS_FILE = os.path.join(DATA_DIR, "drivers.json")
STORAGE_FILE = os.path.join(DATA_DIR, "storage.json")

START_TEXT = "🚀 Старт"
POINT_TEXT = "📍 Геомітка"
FINISH_TEXT = "🏁 Фініш"


# =========================
# Keyboards
# =========================

def main_keyboard():
    return ReplyKeyboardMarkup(
        [
            [START_TEXT],
            [KeyboardButton(POINT_TEXT, request_location=True), FINISH_TEXT],
        ],
        resize_keyboard=True,
    )


# =========================
# JSON helpers
# =========================

def load_json_file(path, default_data):
    if not os.path.exists(path):
        return default_data
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json_file(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def load_drivers():
    data = load_json_file(DRIVERS_FILE, {"drivers": []})
    if "drivers" not in data:
        data = {"drivers": []}
    return data


def save_drivers(data):
    save_json_file(DRIVERS_FILE, data)


def load_storage():
    data = load_json_file(STORAGE_FILE, {"routes": {}})
    if "routes" not in data:
        data = {"routes": {}}
    return data


def save_storage(data):
    save_json_file(STORAGE_FILE, data)


def ensure_data_files_exist():
    if not os.path.exists(DRIVERS_FILE):
        save_drivers({"drivers": []})

    if not os.path.exists(STORAGE_FILE):
        save_storage({"routes": {}})


# =========================
# Driver registry
# =========================

def fallback_name(user):
    return user.first_name or "Водій"


def find_driver_by_user_id(drivers, user_id):
    for d in drivers:
        if d["user_id"] == user_id:
            return d
    return None


def ensure_driver_exists(user):
    data = load_drivers()
    drivers = data["drivers"]

    driver = find_driver_by_user_id(drivers, user.id)

    if not driver:
        driver = {
            "user_id": user.id,
            "username": user.username,
            "display_name": fallback_name(user),
            "is_active": False,
            "role": "driver",
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
        }
        drivers.append(driver)
        save_drivers(data)
        return driver, True

    changed = False

    if driver.get("username") != user.username:
        driver["username"] = user.username
        changed = True

    if not driver.get("display_name"):
        driver["display_name"] = fallback_name(user)
        changed = True

    if changed:
        driver["updated_at"] = datetime.now().isoformat()
        save_drivers(data)

    return driver, False


def is_admin(user_id):
    return user_id in ADMIN_IDS


def require_active_driver(user):
    data = load_drivers()
    driver = find_driver_by_user_id(data["drivers"], user.id)

    if not driver:
        return None, "Тебе ще не додано в систему\nНатисни /start"

    if not driver.get("is_active", False):
        return driver, "Тебе ще не активовано в системі"

    return driver, None


# =========================
# Route/session storage
# =========================

def today_key():
    return datetime.now().strftime("%Y-%m-%d")


def get_route_key(user_id):
    return f"{user_id}:{today_key()}"


def get_or_create_route(storage, user_id):
    route_key = get_route_key(user_id)

    if route_key not in storage["routes"]:
        storage["routes"][route_key] = {
            "user_id": user_id,
            "date": today_key(),
            "status": "idle",
            "state": "idle",
            "pending_location_name": None,
            "pending_location_data": None,
            "distance_km": None,
            "points": [],
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
        }

    return storage["routes"][route_key]


def save_route(storage, route):
    route["updated_at"] = datetime.now().isoformat()
    save_storage(storage)


# =========================
# Admin commands
# =========================

async def drivers_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("Немає доступу")
        return

    data = load_drivers()
    drivers = data["drivers"]

    if not drivers:
        await update.message.reply_text("Список порожній")
        return

    text = "Водії:\n\n"
    for d in drivers:
        status = "🟢" if d.get("is_active") else "🔴"
        username_part = f" | @{d['username']}" if d.get("username") else ""
        text += f"{status} {d['display_name']} (id: {d['user_id']}){username_part}\n"

    await update.message.reply_text(text)


async def activate_driver(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("Немає доступу")
        return

    if not context.args:
        await update.message.reply_text("Формат: /activate 123456789")
        return

    try:
        target_user_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("Формат: /activate 123456789")
        return

    data = load_drivers()
    driver = find_driver_by_user_id(data["drivers"], target_user_id)

    if not driver:
        await update.message.reply_text("Водія не знайдено")
        return

    driver["is_active"] = True
    driver["updated_at"] = datetime.now().isoformat()
    save_drivers(data)

    await update.message.reply_text(f"{driver['display_name']} активовано")


async def deactivate_driver(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("Немає доступу")
        return

    if not context.args:
        await update.message.reply_text("Формат: /deactivate 123456789")
        return

    try:
        target_user_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("Формат: /deactivate 123456789")
        return

    data = load_drivers()
    driver = find_driver_by_user_id(data["drivers"], target_user_id)

    if not driver:
        await update.message.reply_text("Водія не знайдено")
        return

    driver["is_active"] = False
    driver["updated_at"] = datetime.now().isoformat()
    save_drivers(data)

    await update.message.reply_text(f"{driver['display_name']} деактивовано")


async def set_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("Немає доступу")
        return

    if len(context.args) < 2:
        await update.message.reply_text("Формат: /setname 123456789 Саша")
        return

    try:
        target_user_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("Формат: /setname 123456789 Саша")
        return

    new_name = " ".join(context.args[1:]).strip()

    if not new_name:
        await update.message.reply_text("Ім'я не може бути порожнім")
        return

    data = load_drivers()
    driver = find_driver_by_user_id(data["drivers"], target_user_id)

    if not driver:
        await update.message.reply_text("Водія не знайдено")
        return

    driver["display_name"] = new_name
    driver["updated_at"] = datetime.now().isoformat()
    save_drivers(data)

    await update.message.reply_text(f"Ім'я оновлено: {new_name}")


async def chat_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("Немає доступу")
        return

    chat = update.effective_chat
    await update.message.reply_text(f"CHAT ID: {chat.id}")


# =========================
# Driver flow
# =========================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    driver, is_new = ensure_driver_exists(user)

    if is_new:
        await update.message.reply_text(
            f"{driver['display_name']}, доступ зафіксовано",
            reply_markup=main_keyboard(),
        )
        return

    await update.message.reply_text(
        f"{driver['display_name']}, ти вже в системі",
        reply_markup=main_keyboard(),
    )


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = (update.message.text or "").strip()

    if text.startswith("/"):
        return

    driver, error = require_active_driver(user)
    if error:
        await update.message.reply_text(error, reply_markup=main_keyboard())
        return

    storage = load_storage()
    route = get_or_create_route(storage, user.id)

    if text == START_TEXT:
        route["status"] = "active"
        route["state"] = "active"
        route["pending_location_name"] = None
        route["pending_location_data"] = None
        route["distance_km"] = None
        route["points"] = []
        route["started_at"] = datetime.now().isoformat()
        save_route(storage, route)

        await update.message.reply_text("День розпочато", reply_markup=main_keyboard())
        return

    if text == FINISH_TEXT:
        if route["status"] != "active":
            await update.message.reply_text(
                "Спочатку натисни 🚀 Старт",
                reply_markup=main_keyboard(),
            )
            return

        if len(route["points"]) < 2:
            await update.message.reply_text(
                "Недостатньо точок для розрахунку",
                reply_markup=main_keyboard(),
            )
            return

        distance_km = calculate_total_distance_km(route["points"])
        route["distance_km"] = distance_km

        if distance_km <= 0 and not TEST_MODE_ALLOW_ZERO_DISTANCE:
            await update.message.reply_text(
                "Недостатньо коректних даних для розрахунку",
                reply_markup=main_keyboard(),
            )
            return

        route["status"] = "finished"
        route["state"] = "finished"
        route["pending_location_name"] = None
        route["pending_location_data"] = None
        route["finished_at"] = datetime.now().isoformat()
        save_route(storage, route)

        date_text = datetime.now().strftime("%d.%m")

        await update.message.reply_text(
            f"🏁 Маршрут завершено\nФактичний кілометраж: {distance_km} км",
            reply_markup=main_keyboard(),
        )

        if GROUP_CHAT_ID:
            await context.bot.send_message(
                chat_id=GROUP_CHAT_ID,
                text=f"{driver['display_name']} | {date_text}\nФактичний кілометраж: {distance_km} км",
            )
        return

    if route["state"] == "waiting_for_name_after_location":
        point_name = text
        pending_location = route.get("pending_location_data")

        if not pending_location:
            route["state"] = "active"
            route["pending_location_name"] = None
            route["pending_location_data"] = None
            save_route(storage, route)

            await update.message.reply_text(
                "Спочатку натисни 📍 Геомітка",
                reply_markup=main_keyboard(),
            )
            return

        point = {
            "location_name": point_name,
            "latitude": pending_location["latitude"],
            "longitude": pending_location["longitude"],
            "timestamp": datetime.now().isoformat(),
        }

        route["points"].append(point)
        route["pending_location_name"] = None
        route["pending_location_data"] = None
        route["state"] = "active"
        save_route(storage, route)

        await update.message.reply_text(
            f"{point_name} - збережено",
            reply_markup=main_keyboard(),
        )

        if GROUP_CHAT_ID:
            await context.bot.send_message(
                chat_id=GROUP_CHAT_ID,
                text=f"{driver['display_name']} — {point_name}",
            )
            await context.bot.send_location(
                chat_id=GROUP_CHAT_ID,
                latitude=point["latitude"],
                longitude=point["longitude"],
            )
        return

    await update.message.reply_text(
        "Обери дію з кнопок",
        reply_markup=main_keyboard(),
    )


async def handle_location(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    driver, error = require_active_driver(user)

    if error:
        await update.message.reply_text(error, reply_markup=main_keyboard())
        return

    storage = load_storage()
    route = get_or_create_route(storage, user.id)

    if route["status"] != "active":
        await update.message.reply_text(
            "Спочатку натисни 🚀 Старт",
            reply_markup=main_keyboard(),
        )
        return

    location = update.message.location

    if not location:
        await update.message.reply_text(
            "Некоректна геолокація",
            reply_markup=main_keyboard(),
        )
        return

    if location.latitude == 0 and location.longitude == 0:
        await update.message.reply_text(
            "Некоректна геолокація",
            reply_markup=main_keyboard(),
        )
        return

    route["pending_location_data"] = {
        "latitude": location.latitude,
        "longitude": location.longitude,
    }
    route["state"] = "waiting_for_name_after_location"
    save_route(storage, route)

    await update.message.reply_text(
        "Введи назву точки",
        reply_markup=main_keyboard(),
    )


def main():
    if not BOT_TOKEN:
        raise ValueError("BOT_TOKEN is missing in .env")

    ensure_data_files_exist()

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("drivers", drivers_list))
    app.add_handler(CommandHandler("chatid", chat_id))
    app.add_handler(CommandHandler("activate", activate_driver))
    app.add_handler(CommandHandler("deactivate", deactivate_driver))
    app.add_handler(CommandHandler("setname", set_name))

    app.add_handler(MessageHandler(filters.LOCATION, handle_location))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    print("Bot started...")
    app.run_polling()


if __name__ == "__main__":
    main()