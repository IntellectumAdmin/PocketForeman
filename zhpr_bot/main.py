# -*- coding: utf-8 -*-
"""
main.py — точка входа ЖПР-бота INTELLECTUM (модульная версия)
"""

import logging

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)

from zhpr_bot.config import TELEGRAM_BOT_TOKEN
from zhpr_bot.utils.keyboards import main_menu
from zhpr_bot.constants import (
    # кнопки
    BTN_NEW_ENTRY,
    BTN_ADD_SAME,
    BTN_CANCEL,
    # состояния
    ZHPR_DATE,
    ZHPR_SECTION,
    ZHPR_SUBSECTION,
    ZHPR_WORKTYPE,
    ZHPR_PLAN,
    ZHPR_FACT,
    ZHPR_UNIT,
    ZHPR_WORKERS,
    ZHPR_EQUIP_TYPE,
    ZHPR_EQUIP_COUNT,
    ZHPR_COMMENT,
    ZHPR_REVIEW,
    WEATHER_SETUP,
)

from zhpr_bot.dialog.date_step import btn_new_entry, st_date
from zhpr_bot.dialog.section_step import st_section
from zhpr_bot.dialog.subsection_step import st_subsection
from zhpr_bot.dialog.work_step import st_worktype, st_plan, st_fact, st_unit
from zhpr_bot.dialog.people_equip_step import (
    st_workers,
    st_equip_type,
    st_equip_count,
)
from zhpr_bot.dialog.comment_finalize import (
    st_comment,
    st_review,
    btn_add_same_entry,
)
from zhpr_bot.dialog.weather_settings import (
    cmd_weather,
    st_weather_setup,
    cancel_weather,
)


log = logging.getLogger(__name__)


# ===== Базовые команды =====

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /start — приветствие и показ главного меню.
    """
    await update.message.reply_text(
        "👷 Привет! Это ЖПР-бот (Журнал производства работ) INTELLECTUM.\n"
        "Нажми кнопку ниже, чтобы создать новую запись.\n"
        "Для настройки погоды: /weather",
        reply_markup=main_menu(),
    )


async def cancel_conv(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Отмена диалога ЖПР (fallback).
    """
    from telegram.ext import ConversationHandler as Conv

    context.user_data.pop("zhpr", None)
    context.user_data.pop("zhpr_struct", None)

    await update.message.reply_text(
        "Диалог ЖПР отменён.",
        reply_markup=main_menu(),
    )
    return Conv.END


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Обработка обычного текста вне активного диалога:
    - нажата кнопка "Новая запись ЖПР"
    - нажата кнопка "Ещё вид работ (этот же участок)"
    - любой другой текст
    """
    txt = (update.message.text or "").strip()

    if txt == BTN_NEW_ENTRY:
        return await btn_new_entry(update, context)

    if txt == BTN_ADD_SAME:
        return await btn_add_same_entry(update, context)

    await update.message.reply_text(
        "Если хочешь создать запись ЖПР — нажми кнопку или команду /start.",
        reply_markup=main_menu(),
    )


# ===== Сборка приложения =====

def build_application():
    """
    Собирает Application с хендлерами.
    """
    if not TELEGRAM_BOT_TOKEN:
        raise RuntimeError("Нет TELEGRAM_BOT_TOKEN_ZHPR в .env")

    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

    # Диалог настройки погоды
    conv_weather = ConversationHandler(
        entry_points=[CommandHandler("weather", cmd_weather)],
        states={
            WEATHER_SETUP: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, st_weather_setup)
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel_weather)],
        name="weather_conv",
        persistent=False,
    )

    # Диалог ЖПР
    conv_zhpr = ConversationHandler(
        entry_points=[
            MessageHandler(filters.Regex(f"^{BTN_NEW_ENTRY}$"), btn_new_entry),
            MessageHandler(filters.Regex(f"^{BTN_ADD_SAME}$"), btn_add_same_entry),
        ],
        states={
            ZHPR_DATE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, st_date)
            ],
            ZHPR_SECTION: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, st_section)
            ],
            ZHPR_SUBSECTION: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, st_subsection)
            ],
            ZHPR_WORKTYPE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, st_worktype)
            ],
            ZHPR_PLAN: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, st_plan)
            ],
            ZHPR_FACT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, st_fact)
            ],
            ZHPR_UNIT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, st_unit)
            ],
            ZHPR_WORKERS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, st_workers)
            ],
            ZHPR_EQUIP_TYPE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, st_equip_type)
            ],
            ZHPR_EQUIP_COUNT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, st_equip_count)
            ],
            ZHPR_COMMENT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, st_comment)
            ],
            ZHPR_REVIEW: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, st_review)
            ],
        },
        fallbacks=[
            CommandHandler("cancel", cancel_conv),
            MessageHandler(filters.Regex(f"^{BTN_CANCEL}$"), cancel_conv),
        ],
        name="zhpr_conv",
        persistent=False,
    )

    # Регистрация хендлеров
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(conv_weather)
    app.add_handler(conv_zhpr)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))

    return app


def main():
    """
    Точка входа: запуск polling.
    """
    logging.basicConfig(level=logging.INFO)
    log.info("ZHPR Bot — running (modular version)…")

    app = build_application()
    app.run_polling()


if __name__ == "__main__":
    main()
