# -*- coding: utf-8 -*-
"""
people_equip_step.py — рабочие и техника
"""

from telegram import Update
from telegram.ext import ContextTypes

from zhpr_bot.constants import (
    ZHPR_EQUIP_TYPE,
    ZHPR_EQUIP_COUNT,
    ZHPR_WORKERS,
    ZHPR_COMMENT,
)


async def st_workers(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Пользователь вводит количество рабочих (int).
    """
    txt = (update.message.text or "").strip()

    try:
        val = int(txt)
    except ValueError:
        await update.message.reply_text(
            "Нужно целое число. Попробуй ещё раз (пример: 5 или 12)."
        )
        return ZHPR_WORKERS

    context.user_data["zhpr"]["workers"] = val

    await update.message.reply_text(
        "Введи *типы техники*, если была.\n"
        "Например: Экскаватор, Автокран.\n"
        "Если техники не было — напиши -.",
        parse_mode="Markdown",
    )
    return ZHPR_EQUIP_TYPE


async def st_equip_type(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Пользователь вводит типы техники.
    Пример: "Экскаватор, Автокран"
    """
    txt = (update.message.text or "").strip()

    if txt in ("-", "—", ""):
        context.user_data["zhpr"]["equip_types"] = []
    else:
        types_ = [t.strip() for t in txt.split(",") if t.strip()]
        context.user_data["zhpr"]["equip_types"] = types_

    await update.message.reply_text(
        "Теперь напиши *количество техники* текстом.\n"
        "Например: 1 экскаватор, 1 кран, 0.5 смены насоса.\n"
        "Или -, если не было.",
        parse_mode="Markdown",
    )
    return ZHPR_EQUIP_COUNT


async def st_equip_count(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Текстовое количество техники.
    """
    txt = (update.message.text or "").strip()

    if txt in ("-", "—", ""):
        context.user_data["zhpr"]["equip_count"] = ""
    else:
        context.user_data["zhpr"]["equip_count"] = txt

    await update.message.reply_text(
        "Добавь комментарий (что важно запомнить).\n"
        "Например: Отставание из-за поздней поставки бетона, Готово под приёмку.\n"
        "Или напиши -, чтобы пропустить.",
        parse_mode="Markdown",
    )

    return ZHPR_COMMENT
