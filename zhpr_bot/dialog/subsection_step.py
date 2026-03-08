# -*- coding: utf-8 -*-
"""
subsection_step.py — ввод подраздела / участка для записи ЖПР
"""

from telegram import Update
from telegram.ext import ContextTypes

from zhpr_bot.constants import ZHPR_WORKTYPE


async def st_subsection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Пользователь вводит текстом подраздел / участок.
    Пример: "Цоколь / входная группа" или "Блок А, оси 1-5".
    """
    text = (update.message.text or "").strip()
    context.user_data["zhpr"]["subsection"] = text

    await update.message.reply_text(
        "Введи *вид работ*.\n"
        "Например: Бетон, Кирпич, Отделка.\n"
        "Если несколько — напиши через запятую.",
        parse_mode="Markdown",
    )

    return ZHPR_WORKTYPE
