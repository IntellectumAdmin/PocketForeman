# -*- coding: utf-8 -*-
"""
date_step.py — старт диалога ЖПР: кнопка "Новая запись ЖПР" и умная дата.
"""

from datetime import datetime, date, timedelta

from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import ContextTypes

from zhpr_bot.constants import BTN_DATE_KEEP, ZHPR_DATE
from zhpr_bot.services.zhpr_queries import get_last_zhpr_date
from zhpr_bot.dialog.section_step import start_section_selection


async def btn_new_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Старт новой записи ЖПР: сначала спрашиваем дату.
    """
    context.user_data["zhpr"] = {}

    today = date.today()
    last_date = get_last_zhpr_date()

    lines = [f"Сегодня: {today.strftime('%d.%m.%Y')}"]
    suggested = today

    if last_date is None:
        lines.append("В ЖПР пока нет записей. Начинаем с сегодняшнего дня.")
    else:
        last_str = last_date.strftime("%d.%m.%Y")

        if last_date == today:
            lines.append(f"Последняя запись в ЖПР уже за сегодня ({last_str}).")
            lines.append("Оставляю сегодняшнюю дату.")
            suggested = today

        elif last_date < today:
            diff = (today - last_date).days
            lines.append(f"Последняя запись в ЖПР: {last_str}.")
            if diff == 1:
                lines.append("Вчерашний день заполнен. По умолчанию ставлю сегодня.")
                suggested = today
            else:
                suggested = last_date + timedelta(days=1)
                s_str = suggested.strftime("%d.%m.%Y")
                lines.append("Похоже, есть пропущенные дни.")
                lines.append(f"По умолчанию ставлю дату: {s_str}.")
        else:
            lines.append(f"Последняя запись в ЖПР: {last_str}.")
            lines.append("Но дата в будущем, поэтому ставлю сегодня.")

    context.user_data["zhpr"]["date_obj"] = datetime.combine(
        suggested, datetime.min.time()
    )

    msg = "\n".join(lines) + (
        "\n\nЕсли эта дата подходит — нажми «✅ Оставить».\n"
        "Или напиши другую дату в формате ДД.ММ.ГГГГ (например: 23.11.2025)."
    )

    await update.message.reply_text(
        msg,
        reply_markup=ReplyKeyboardMarkup([[BTN_DATE_KEEP]], resize_keyboard=True),
    )

    return ZHPR_DATE


async def st_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Обработка ответа пользователя с датой.
    """
    txt = (update.message.text or "").strip()

    if txt == BTN_DATE_KEEP:
        # Переходим к выбору раздела
        return await start_section_selection(update, context)

    # Пытаемся распарсить дату руками
    try:
        d = datetime.strptime(txt, "%d.%m.%Y").date()
    except ValueError:
        await update.message.reply_text(
            "Не понял дату. Введи в формате ДД.ММ.ГГГГ, например: 23.11.2025\n"
            "Или нажми «✅ Оставить», чтобы взять предложенную дату."
        )
        return ZHPR_DATE

    context.user_data["zhpr"]["date_obj"] = datetime.combine(d, datetime.min.time())
    return await start_section_selection(update, context)
