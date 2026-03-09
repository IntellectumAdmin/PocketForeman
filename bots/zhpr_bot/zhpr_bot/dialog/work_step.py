# -*- coding: utf-8 -*-
"""
work_step.py — вид работ, объёмы план/факт и единица измерения
"""

from telegram import Update
from telegram.ext import ContextTypes

from zhpr_bot.constants import (
    ZHPR_PLAN,
    ZHPR_FACT,
    ZHPR_UNIT,
    ZHPR_WORKTYPE,
)


async def st_worktype(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Пользователь вводит вид(ы) работ.
    Допускаются несколько через запятую, но в Notion уйдёт только первый как основной.
    """
    txt = (update.message.text or "").strip()
    worktypes = [w.strip() for w in txt.split(",") if w.strip()]

    context.user_data["zhpr"]["worktypes"] = worktypes

    await update.message.reply_text(
        "Введи *объём по плану (на день)* числом.\n"
        "Например: 25",
        parse_mode="Markdown",
    )
    return ZHPR_PLAN


async def st_plan(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Ввод планового объёма за день (float).
    """
    txt = (update.message.text or "").replace(",", ".").strip()

    try:
        val = float(txt)
    except ValueError:
        await update.message.reply_text(
            "Нужно число. Попробуй ещё раз (пример: 25 или 12.5)."
        )
        return ZHPR_PLAN

    context.user_data["zhpr"]["plan"] = val

    await update.message.reply_text(
        "Теперь введи *фактический объём за день* числом.\n"
        "Например: 18",
        parse_mode="Markdown",
    )
    return ZHPR_FACT


async def st_fact(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Ввод фактического объёма за день (float).
    """
    txt = (update.message.text or "").replace(",", ".").strip()

    try:
        val = float(txt)
    except ValueError:
        await update.message.reply_text(
            "Нужно число. Попробуй ещё раз (пример: 18 или 9.5)."
        )
        return ZHPR_FACT

    context.user_data["zhpr"]["fact"] = val

    await update.message.reply_text(
        "Введи *единицу измерения* (например: м³, м², шт, п.м.).",
        parse_mode="Markdown",
    )
    return ZHPR_UNIT


async def st_unit(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Ввод единицы измерения (строка).
    """
    txt = (update.message.text or "").strip()
    context.user_data["zhpr"]["unit"] = txt

    await update.message.reply_text(
        "Сколько было рабочих на этом участке? Введи число.\nНапример: 6"
    )
    # дальше идём на шаг рабочих/техники
    from zhpr_bot.constants import ZHPR_WORKERS  # импорт здесь, чтобы избежать циклов

    return ZHPR_WORKERS
