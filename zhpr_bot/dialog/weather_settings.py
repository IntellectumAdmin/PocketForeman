# -*- coding: utf-8 -*-
"""
weather_settings.py — настройка города/координат для автопогоды (/weather)
"""

from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler

from zhpr_bot.constants import WEATHER_SETUP
from zhpr_bot.utils.keyboards import main_menu
from zhpr_bot.services.weather_service import set_user_location


async def cmd_weather(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Старт диалога настройки погоды.
    """
    text = (
        "🌤 Настройка погоды для ЖПР.\n\n"
        "Напиши город, например: *Уральск*\n"
        "или координаты в формате: 51.233, 51.383.\n\n"
        "Если хочешь отключить автопогоду — напиши -."
    )
    await update.message.reply_text(text, parse_mode="Markdown")
    return WEATHER_SETUP


async def st_weather_setup(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Обработка введённого города/координат или отключения погоды.
    """
    txt = (update.message.text or "").strip()
    user = update.effective_user

    if txt in ("-", "—"):
        set_user_location(user.id, None)
        await update.message.reply_text(
            "Автопогода для ЖПР отключена.",
            reply_markup=main_menu(),
        )
        return ConversationHandler.END

    set_user_location(user.id, txt)
    await update.message.reply_text(
        f"Город (или координаты) для погоды установлен(ы): {txt}",
        reply_markup=main_menu(),
    )
    return ConversationHandler.END


async def cancel_weather(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Отмена настройки погоды.
    """
    await update.message.reply_text(
        "Настройка погоды отменена.",
        reply_markup=main_menu(),
    )
    return ConversationHandler.END
