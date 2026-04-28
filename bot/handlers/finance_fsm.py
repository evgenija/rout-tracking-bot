"""
finance_fsm.py — FSM щоденного вводу виручки та sales km.
Кнопка "💰 Фін модель" → перевірка маршрутів → revenue → sales_km → звіт.
Тільки для super-admin.
"""
import logging
from datetime import date

from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    Message, ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery,
)
from aiogram.filters import Command

from config_p2 import SUPER_ADMIN_IDS
from bot.services.finance_service import (
    get_open_routes_for_date,
    save_period_input,
    get_daily_op_result,
)
from bot.services.report_service import format_daily_op_report
from bot.utils.keyboards import kb_admin_main
from bot.utils.time_utils import get_kyiv_time

logger = logging.getLogger(__name__)
router = Router()

_pg_pool = None
_coeff_service = None


def setup_finance_fsm(pg_pool, coeff_service):
    global _pg_pool, _coeff_service
    _pg_pool = pg_pool
    _coeff_service = coeff_service


class RevenueInput(StatesGroup):
    waiting_revenue  = State()
    waiting_sales_km = State()


def _is_super_admin(user_id: int) -> bool:
    return user_id in SUPER_ADMIN_IDS


_cancel_kb = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="❌ Скасувати")]],
    resize_keyboard=True,
    one_time_keyboard=True,
)

_cancel_km_kb = ReplyKeyboardMarkup(
    keyboard=[[
        KeyboardButton(text="◀ Змінити виручку"),
        KeyboardButton(text="❌ Скасувати"),
    ]],
    resize_keyboard=True,
    one_time_keyboard=True,
)


def _delete_kb(target_date: date) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(
            text="🗑 Видалити цей запис",
            callback_data=f"fin_del:{target_date.isoformat()}",
        )
    ]])


@router.message(F.text == "💰 Фін модель")
async def btn_finance(message: Message, state: FSMContext):
    if not _is_super_admin(message.from_user.id):
        return

    today = get_kyiv_time().date()
    open_routes = await get_open_routes_for_date(today)

    if open_routes:
        names = ", ".join(r.get("full_name") or f"ID {r['id']}" for r in open_routes)
        await message.answer(
            f"⏳ Є незакриті маршрути за {today.strftime('%d.%m.%Y')}:\n"
            f"{names}\n\n"
            f"Операційний прибуток покажу після їх закриття.\n"
            f"Або введи виручку зараз (без урахування відкритих маршрутів).",
        )

    await message.answer(
        f"💰 Введіть виручку за {today.strftime('%d.%m.%Y')} (грн):\n"
        f"Наприклад: 850000",
        reply_markup=_cancel_kb,
    )
    await state.set_state(RevenueInput.waiting_revenue)
    await state.update_data(input_date=today.isoformat())


@router.message(F.text == "❌ Скасувати")
async def cancel_input(message: Message, state: FSMContext):
    if not _is_super_admin(message.from_user.id):
        return
    await state.clear()
    await message.answer("Скасовано.", reply_markup=kb_admin_main())


@router.message(F.text == "◀ Змінити виручку", RevenueInput.waiting_sales_km)
async def back_to_revenue(message: Message, state: FSMContext):
    if not _is_super_admin(message.from_user.id):
        return
    data = await state.get_data()
    input_date = date.fromisoformat(data["input_date"])
    await state.set_state(RevenueInput.waiting_revenue)
    await message.answer(
        f"💰 Введіть виручку за {input_date.strftime('%d.%m.%Y')} (грн):\n"
        f"Наприклад: 850000",
        reply_markup=_cancel_kb,
    )


@router.message(RevenueInput.waiting_revenue)
async def process_revenue(message: Message, state: FSMContext):
    if not _is_super_admin(message.from_user.id):
        return

    text = message.text.strip().replace(" ", "").replace(",", "")
    if not text.isdigit() or int(text) <= 0:
        await message.answer(
            "❌ Введіть суму в гривнях цілим числом > 0\n"
            "Наприклад: 850000",
            reply_markup=_cancel_kb,
        )
        return

    revenue = int(text)
    await state.update_data(revenue=revenue)
    await message.answer(
        f"✅ Виручка: {revenue:,} грн\n\n"
        f"🚗 Кілометри sales-менеджерів за {date.fromisoformat((await state.get_data())['input_date']).strftime('%d.%m.%Y')}:\n"
        f"(Введіть 0 якщо не їздили)",
        reply_markup=_cancel_km_kb,
    )
    await state.set_state(RevenueInput.waiting_sales_km)


@router.message(RevenueInput.waiting_sales_km)
async def process_sales_km(message: Message, state: FSMContext):
    if not _is_super_admin(message.from_user.id):
        return

    text = message.text.strip().replace(" ", "")
    if not text.isdigit():
        await message.answer(
            "❌ Введіть кілометри цілим числом ≥ 0\n"
            "Наприклад: 550 або 0",
            reply_markup=_cancel_kb,
        )
        return

    sales_km = int(text)
    data = await state.get_data()
    await state.clear()

    revenue    = data["revenue"]
    input_date = date.fromisoformat(data["input_date"])

    saved = await save_period_input(
        pg_pool=_pg_pool,
        date_from=input_date,
        date_to=input_date,
        revenue=revenue,
        sales_km=sales_km,
    )

    if not saved:
        await message.answer(
            "❌ Помилка збереження. Можливо, виручка за цю дату вже введена.\n"
            "Переглянь список через /finance_list.",
            reply_markup=kb_admin_main(),
        )
        return

    try:
        coefficients = await _coeff_service.get()
        result = await get_daily_op_result(_pg_pool, input_date, coefficients)

        if result is None:
            await message.answer(
                "✅ Збережено!\n\n"
                "⚠️ Не вдалося розрахувати Op.Profit — перевірте дані доставки.",
                reply_markup=kb_admin_main(),
            )
            await message.answer(
                "Якщо дані введені помилково — видали запис кнопкою нижче та введи знову.",
                reply_markup=_delete_kb(input_date),
            )
            return

        report_text = format_daily_op_report(result)

        if sales_km == 0:
            alert = (
                f"⚠️ Sales км = 0 за {input_date.strftime('%d.%m.%Y')}\n"
                f"Операційний прибуток може бути завищений.\n"
                f"Якщо sales-менеджери їздили — відкрий /finance_list і виправ запис."
            )
            for admin_id in SUPER_ADMIN_IDS:
                if admin_id != message.from_user.id:
                    try:
                        from bot.main import bot as _bot
                        await _bot.send_message(admin_id, alert)
                    except Exception:
                        pass

        await message.answer(report_text, reply_markup=kb_admin_main())
        await message.answer(
            "Якщо дані введені помилково — видали запис кнопкою нижче та введи знову.",
            reply_markup=_delete_kb(input_date),
        )

    except Exception as e:
        logger.exception("finance_fsm: report generation failed: %s", e)
        await message.answer(
            "✅ Дані збережено!\n\n"
            "⚠️ Не вдалося згенерувати звіт. Спробуйте /daily_report.",
            reply_markup=kb_admin_main(),
        )
        await message.answer(
            "Якщо дані введені помилково — видали запис кнопкою нижче та введи знову.",
            reply_markup=_delete_kb(input_date),
        )


@router.message(Command("finance_list"))
async def cmd_finance_list(message: Message):
    if not _is_super_admin(message.from_user.id):
        return
    if _pg_pool is None:
        await message.answer("⚠️ БД недоступна.")
        return
    try:
        async with _pg_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT date_from, date_to, revenue, sales_km
                FROM period_input
                WHERE date_from >= CURRENT_DATE - INTERVAL '14 days'
                ORDER BY date_from DESC
                """,
            )
        if not rows:
            await message.answer("📋 Записів за останні 14 днів немає.")
            return

        await message.answer("📋 Введена виручка (14 днів):")

        for r in rows:
            d_from = r["date_from"].strftime("%d.%m")
            d_to   = r["date_to"].strftime("%d.%m.%Y")
            period = d_from if r["date_from"] == r["date_to"] else f"{d_from}–{d_to}"
            revenue_fmt = f"{r['revenue']:,}".replace(",", " ")
            await message.answer(
                f"📅 {period} | 💰 {revenue_fmt} грн | 🚗 {r['sales_km']} км",
                reply_markup=_delete_kb(r["date_from"]),
            )

    except Exception as e:
        logger.exception("finance_list failed: %s", e)
        await message.answer(f"⚠️ Помилка: {e}")


@router.callback_query(F.data.startswith("fin_del:"))
async def cb_finance_delete(callback: CallbackQuery):
    if not _is_super_admin(callback.from_user.id):
        await callback.answer("⛔ Немає доступу.", show_alert=True)
        return
    if _pg_pool is None:
        await callback.answer("⚠️ БД недоступна.", show_alert=True)
        return

    date_str = callback.data[len("fin_del:"):]
    try:
        target_date = date.fromisoformat(date_str)
    except ValueError:
        await callback.answer("❌ Невірна дата.", show_alert=True)
        return

    try:
        async with _pg_pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT revenue, sales_km, date_from, date_to FROM period_input "
                "WHERE date_from <= $1 AND date_to >= $1",
                target_date,
            )
            if row is None:
                await callback.answer(
                    f"Запис за {target_date.strftime('%d.%m.%Y')} вже видалено або не існує.",
                    show_alert=True,
                )
                await callback.message.edit_reply_markup(reply_markup=None)
                return

            await conn.execute(
                "DELETE FROM period_input WHERE date_from <= $1 AND date_to >= $1",
                target_date,
            )

        d_from = row["date_from"].strftime("%d.%m")
        d_to   = row["date_to"].strftime("%d.%m.%Y")
        period = d_from if row["date_from"] == row["date_to"] else f"{d_from}–{d_to}"
        revenue_fmt = f"{row['revenue']:,}".replace(",", " ")

        await callback.message.edit_text(
            f"🗑 Видалено: {period} | {revenue_fmt} грн | {row['sales_km']} км\n"
            f"Введи знову через 💰 Фін модель.",
        )
        await callback.answer("Видалено ✅")
        logger.info(
            "fin_del callback: user=%d deleted period_input for %s",
            callback.from_user.id, target_date,
        )

    except Exception as e:
        logger.exception("fin_del callback failed: %s", e)
        await callback.answer(f"⚠️ Помилка: {e}", show_alert=True)
