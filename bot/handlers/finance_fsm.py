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
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove

from config_p2 import SUPER_ADMIN_IDS
from bot.services.finance_service import (
    get_open_routes_for_date,
    save_period_input,
    get_daily_op_result,
    get_delivery_totals_for_date,
)
from bot.services.report_service import format_daily_op_report
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
    await message.answer("Скасовано.", reply_markup=ReplyKeyboardRemove())


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
        reply_markup=_cancel_kb,
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

    # Зберігаємо в period_input
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
            "Перевір /finance_list або зверніться до адміна.",
            reply_markup=ReplyKeyboardRemove(),
        )
        return

    # Розраховуємо і показуємо звіт
    try:
        coefficients = await _coeff_service.get()
        result = await get_daily_op_result(_pg_pool, input_date, coefficients)

        if result is None:
            await message.answer(
                "✅ Збережено!\n\n"
                "⚠️ Не вдалося розрахувати Op.Profit — перевірте дані доставки.",
                reply_markup=ReplyKeyboardRemove(),
            )
            return

        report_text = format_daily_op_report(result)

        # Попередження якщо sales_km = 0 — повідомити всіх super-admin
        if sales_km == 0:
            alert = (
                f"⚠️ Sales км = 0 за {input_date.strftime('%d.%m.%Y')}\n"
                f"Операційний прибуток може бути завищений.\n"
                f"Якщо sales-менеджери їздили — введи /set_sales_km {input_date.isoformat()} <км>"
            )
            for admin_id in SUPER_ADMIN_IDS:
                if admin_id != message.from_user.id:
                    try:
                        from bot.main import bot as _bot
                        await _bot.send_message(admin_id, alert)
                    except Exception:
                        pass

        await message.answer(report_text, reply_markup=ReplyKeyboardRemove())

    except Exception as e:
        logger.exception("finance_fsm: report generation failed: %s", e)
        await message.answer(
            "✅ Дані збережено!\n\n"
            "⚠️ Не вдалося згенерувати звіт. Спробуйте /daily_report.",
            reply_markup=ReplyKeyboardRemove(),
        )
