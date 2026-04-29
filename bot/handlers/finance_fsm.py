"""
finance_fsm.py — FSM щоденного та пакетного вводу виручки та sales km.
Кнопка "💰 Фін модель" → перевірка маршрутів → revenue → sales_km → звіт.
batch_revenue callback → пакетний ввід за діапазон дат (з scheduler).
Тільки для super-admin.
"""
import logging
from datetime import date, timedelta

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
    build_weekly_result,
    build_monthly_result,
)
from bot.services.report_service import format_daily_op_report
from bot.services.report_service_finance import (
    format_weekly_report_finance,
    format_monthly_report_finance,
)
from bot.utils.keyboards import kb_admin_main, kb_fin_menu, kb_fin_reports_menu
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


class BatchRevenueInput(StatesGroup):
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
        await message.answer("⛔ Фін модель доступна тільки для супер-адмінів.")
        return
    await state.clear()
    await message.answer("💰 Фін модель:", reply_markup=kb_fin_menu())


@router.callback_query(F.data == "fin:enter")
async def cb_fin_enter(callback: CallbackQuery, state: FSMContext):
    if not _is_super_admin(callback.from_user.id):
        await callback.answer("⛔ Недостатньо прав.", show_alert=True)
        return
    await callback.answer()

    today = get_kyiv_time().date()
    open_routes = await get_open_routes_for_date(today)

    if open_routes:
        names = ", ".join(r.get("full_name") or f"ID {r['id']}" for r in open_routes)
        await callback.message.answer(
            f"⏳ Є незакриті маршрути за {today.strftime('%d.%m.%Y')}:\n"
            f"{names}\n\n"
            f"Операційний прибуток покажу після їх закриття.\n"
            f"Або введи виручку зараз (без урахування відкритих маршрутів).",
        )

    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(
        f"💰 Введіть виручку за {today.strftime('%d.%m.%Y')} (грн):\n"
        f"Наприклад: 850000",
        reply_markup=_cancel_kb,
    )
    await state.set_state(RevenueInput.waiting_revenue)
    await state.update_data(input_date=today.isoformat())


@router.callback_query(F.data == "fin:reports")
async def cb_fin_reports(callback: CallbackQuery):
    if not _is_super_admin(callback.from_user.id):
        await callback.answer("⛔ Недостатньо прав.", show_alert=True)
        return
    await callback.answer()
    await callback.message.edit_reply_markup(reply_markup=kb_fin_reports_menu())


@router.callback_query(F.data == "fin:back")
async def cb_fin_back(callback: CallbackQuery):
    if not _is_super_admin(callback.from_user.id):
        await callback.answer()
        return
    await callback.answer()
    await callback.message.edit_reply_markup(reply_markup=kb_fin_menu())


@router.callback_query(F.data == "fin:rpt:daily")
async def cb_fin_rpt_daily(callback: CallbackQuery):
    if not _is_super_admin(callback.from_user.id):
        await callback.answer("⛔ Недостатньо прав.", show_alert=True)
        return
    if _pg_pool is None or _coeff_service is None:
        await callback.answer("⚠️ БД недоступна.", show_alert=True)
        return
    await callback.answer()
    today = get_kyiv_time().date()
    try:
        coefficients = await _coeff_service.get()
        result = await get_daily_op_result(_pg_pool, today, coefficients)
        if result is None:
            await callback.message.answer(
                f"⚠️ Немає даних за {today.strftime('%d.%m.%Y')}.\n"
                f"Спочатку введіть виручку через 📥 Ввести виручку."
            )
            return
        await callback.message.answer(format_daily_op_report(result))
    except Exception as e:
        logger.exception("fin:rpt:daily failed: %s", e)
        await callback.message.answer(f"⚠️ Помилка генерації звіту: {e}")


@router.callback_query(F.data == "fin:rpt:weekly")
async def cb_fin_rpt_weekly(callback: CallbackQuery):
    if not _is_super_admin(callback.from_user.id):
        await callback.answer("⛔ Недостатньо прав.", show_alert=True)
        return
    if _pg_pool is None or _coeff_service is None:
        await callback.answer("⚠️ БД недоступна.", show_alert=True)
        return
    await callback.answer()
    today = get_kyiv_time().date()
    week_start = today - timedelta(days=today.weekday())
    open_routes = await get_open_routes_for_date(today)
    if open_routes:
        names = ", ".join(r.get("full_name") or f"ID {r['id']}" for r in open_routes)
        await callback.message.answer(
            f"⚠️ Незакриті маршрути: {names}\n"
            f"Дані за {today.strftime('%d.%m')} можуть бути неповні."
        )
    try:
        coefficients = await _coeff_service.get()
        result = await build_weekly_result(_pg_pool, week_start, today, coefficients)
        await callback.message.answer(format_weekly_report_finance(result))
    except Exception as e:
        logger.exception("fin:rpt:weekly failed: %s", e)
        await callback.message.answer(f"⚠️ Помилка генерації звіту: {e}")


@router.callback_query(F.data == "fin:rpt:monthly")
async def cb_fin_rpt_monthly(callback: CallbackQuery):
    if not _is_super_admin(callback.from_user.id):
        await callback.answer("⛔ Недостатньо прав.", show_alert=True)
        return
    if _pg_pool is None or _coeff_service is None:
        await callback.answer("⚠️ БД недоступна.", show_alert=True)
        return
    await callback.answer()
    today = get_kyiv_time().date()
    open_routes = await get_open_routes_for_date(today)
    if open_routes:
        names = ", ".join(r.get("full_name") or f"ID {r['id']}" for r in open_routes)
        await callback.message.answer(
            f"⚠️ Незакриті маршрути: {names}\n"
            f"Дані за {today.strftime('%d.%m')} можуть бути неповні."
        )
    try:
        coefficients = await _coeff_service.get()
        result = await build_monthly_result(_pg_pool, today.year, today.month, coefficients)
        await callback.message.answer(format_monthly_report_finance(result, today.month))
    except Exception as e:
        logger.exception("fin:rpt:monthly failed: %s", e)
        await callback.message.answer(f"⚠️ Помилка генерації звіту: {e}")


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
            "⚠️ Не вдалося згенерувати звіт. Спробуйте через 💰 Фін модель → 📊 Звіти P&L.",
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


# ── Пакетний ввід виручки + sales_km за діапазон дат ──────────────────────────
# Точка входу: inline-кнопка "📥 Ввести за ... одразу" зі scheduler-нотифікації

@router.callback_query(F.data.startswith("batch_revenue:"))
async def cb_batch_revenue_start(callback: CallbackQuery, state: FSMContext):
    if not _is_super_admin(callback.from_user.id):
        await callback.answer()
        return
    parts = callback.data.split(":")
    # формат: batch_revenue:YYYY-MM-DD:YYYY-MM-DD
    try:
        date_from = date.fromisoformat(parts[1])
        date_to   = date.fromisoformat(parts[2])
    except (IndexError, ValueError):
        await callback.answer("❌ Невірний формат дат.", show_alert=True)
        return
    period_str = f"{date_from.strftime('%d.%m')}–{date_to.strftime('%d.%m.%Y')}"
    await state.update_data(batch_date_from=date_from.isoformat(), batch_date_to=date_to.isoformat())
    await state.set_state(BatchRevenueInput.waiting_revenue)
    await callback.message.answer(
        f"📥 Пакетний ввід за {period_str}\n\n"
        f"💰 Введіть загальну суму виручки (грн):\n"
        f"Наприклад: 4250000",
        reply_markup=_cancel_kb,
    )
    await callback.answer()


@router.message(F.text == "◀ Змінити виручку", BatchRevenueInput.waiting_sales_km)
async def back_to_batch_revenue(message: Message, state: FSMContext):
    if not _is_super_admin(message.from_user.id):
        return
    data = await state.get_data()
    date_from  = date.fromisoformat(data["batch_date_from"])
    date_to    = date.fromisoformat(data["batch_date_to"])
    period_str = f"{date_from.strftime('%d.%m')}–{date_to.strftime('%d.%m.%Y')}"
    await state.set_state(BatchRevenueInput.waiting_revenue)
    await message.answer(
        f"💰 Введіть загальну суму виручки за {period_str} (грн):\n"
        f"Наприклад: 4250000",
        reply_markup=_cancel_kb,
    )


@router.message(BatchRevenueInput.waiting_revenue)
async def batch_process_revenue(message: Message, state: FSMContext):
    if not _is_super_admin(message.from_user.id):
        return
    text = message.text.strip().replace(" ", "").replace(",", "")
    if not text.isdigit() or int(text) <= 0:
        await message.answer(
            "❌ Введіть суму в гривнях цілим числом > 0\n"
            "Наприклад: 4250000",
            reply_markup=_cancel_kb,
        )
        return
    revenue = int(text)
    data = await state.get_data()
    await state.update_data(batch_revenue=revenue)
    date_from  = date.fromisoformat(data["batch_date_from"])
    date_to    = date.fromisoformat(data["batch_date_to"])
    period_str = f"{date_from.strftime('%d.%m')}–{date_to.strftime('%d.%m.%Y')}"
    await message.answer(
        f"✅ Виручка: {revenue:,} грн\n\n"
        f"🚗 Кілометри sales-менеджерів за {period_str}:\n"
        f"(Введіть 0 якщо не їздили)",
        reply_markup=_cancel_km_kb,
    )
    await state.set_state(BatchRevenueInput.waiting_sales_km)


@router.message(BatchRevenueInput.waiting_sales_km)
async def batch_process_sales_km(message: Message, state: FSMContext):
    if not _is_super_admin(message.from_user.id):
        return
    text = message.text.strip().replace(" ", "")
    if not text.isdigit():
        await message.answer(
            "❌ Введіть кілометри цілим числом ≥ 0\n"
            "Наприклад: 1200 або 0",
            reply_markup=_cancel_kb,
        )
        return
    sales_km = int(text)
    data = await state.get_data()
    await state.clear()
    revenue   = data["batch_revenue"]
    date_from = date.fromisoformat(data["batch_date_from"])
    date_to   = date.fromisoformat(data["batch_date_to"])
    period_str = f"{date_from.strftime('%d.%m')}–{date_to.strftime('%d.%m.%Y')}"

    saved = await save_period_input(
        pg_pool=_pg_pool,
        date_from=date_from,
        date_to=date_to,
        revenue=revenue,
        sales_km=sales_km,
    )

    if not saved:
        await message.answer(
            f"❌ Помилка збереження. Можливо, виручка за {period_str} вже частково введена.\n"
            "Переглянь список через /finance_list.",
            reply_markup=kb_admin_main(),
        )
        return

    revenue_fmt = f"{revenue:,}".replace(",", " ")
    await message.answer(
        f"✅ Збережено!\n"
        f"📅 Період: {period_str}\n"
        f"💰 Виручка: {revenue_fmt} грн\n"
        f"🚗 Sales км: {sales_km}",
        reply_markup=kb_admin_main(),
    )

    # Op.Profit за кожен день діапазону — сумарний результат
    try:
        coefficients = await _coeff_service.get()
        daily_results = []
        zero_delivery_days = []
        d = date_from
        while d <= date_to:
            r = await get_daily_op_result(_pg_pool, d, coefficients)
            if r is not None:
                daily_results.append(r)
                if r.delivery_total == 0:
                    zero_delivery_days.append(d)
            d += timedelta(days=1)

        if not daily_results:
            return

        def fmt(v: float) -> str:
            return f"{v:,.0f}".replace(",", " ") + " грн"

        total_revenue   = sum(r.revenue        for r in daily_results)
        total_cogs      = sum(r.cogs           for r in daily_results)
        total_delivery  = sum(r.delivery_total for r in daily_results)
        total_sales_km  = sum(r.sales_km_cost  for r in daily_results)
        total_salary    = sum(r.sales_salary   for r in daily_results)
        total_op        = sum(r.op_profit      for r in daily_results)

        lines = [
            f"📊 Операційний результат за {period_str}",
            "",
            f"💰 Виручка:              {fmt(total_revenue)}",
            f"📦 Собівартість (70%):  -{fmt(total_cogs)}",
            f"🚚 Доставка:            -{fmt(total_delivery)}",
            f"👔 Sales км:            -{fmt(total_sales_km)}",
            f"💼 Зарплата sales:      -{fmt(total_salary)}",
            "─" * 36,
            f"{'✅' if total_op >= 0 else '🔴'} Операційний прибуток:  {fmt(total_op)}",
        ]
        if zero_delivery_days:
            days_str = ", ".join(d.strftime("%d.%m") for d in zero_delivery_days)
            lines.append(f"\n⚠️ Дні без даних доставки: {days_str}")
            lines.append("Op.Profit може бути завищений для цих днів.")

        await message.answer("\n".join(lines))
    except Exception as e:
        logger.exception("batch Op.Profit report failed: %s", e)
