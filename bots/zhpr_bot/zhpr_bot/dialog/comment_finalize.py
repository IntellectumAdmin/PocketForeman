# -*- coding: utf-8 -*-
"""
comment_finalize.py — комментарий, погода, ответственный и финальное подтверждение ЖПР
"""

from copy import deepcopy
from datetime import datetime

from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import ContextTypes, ConversationHandler

from zhpr_bot.constants import (
    ZHPR_COMMENT,
    ZHPR_REVIEW,
    ZHPR_WORKTYPE,
    BTN_SAVE,
    BTN_FIX,
    BTN_CANCEL,
    BTN_ADD_SAME,
    BTN_NEW_ENTRY,
)
from zhpr_bot.utils.keyboards import main_menu
from zhpr_bot.services.weather_service import get_user_location, fetch_weather_text
from zhpr_bot.services.id_generator import generate_zhpr_id
from zhpr_bot.services.notion_jpr import create_notion_page_from_context


async def st_comment(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Пользователь вводит комментарий.
    Здесь же:
    - подтягиваем погоду (если настроена)
    - проставляем ответственного
    - генерируем ID ЖПР
    - собираем итоговый текст для проверки
    """
    txt = (update.message.text or "").strip()

    if txt in ("-", "—", ""):
        context.user_data["zhpr"]["comment"] = ""
    else:
        context.user_data["zhpr"]["comment"] = txt

    user = update.effective_user

    # Погода: пробуем получить по сохранённому городу/координатам
    weather_text = None
    loc = get_user_location(user.id)
    if loc:
        weather_text = fetch_weather_text(loc)

    if weather_text:
        context.user_data["zhpr"]["weather"] = weather_text
    else:
        context.user_data["zhpr"].setdefault("weather", "")

    # Ответственный
    context.user_data["zhpr"]["responsible"] = (
        user.full_name or (user.username or "Прораб")
    )

    # Генерация ID ЖПР
    ud = context.user_data["zhpr"]
    date_obj: datetime = ud.get("date_obj", datetime.now())
    zhpr_id = generate_zhpr_id(date_obj)
    context.user_data["zhpr"]["zhpr_id"] = zhpr_id

    # Формируем текст проверки
    text_lines = [
        "ПРОВЕРЬ ЗАПИСЬ ЖПР перед сохранением:",
        "",
        f"ID: {zhpr_id}",
        f"Дата: {date_obj.strftime('%d.%m.%Y')}",
        f"Раздел: {ud.get('section')}",
        f"Участок: {ud.get('subsection')}",
        f"Вид работ: {', '.join(ud.get('worktypes', [])) or '—'}",
        f"План: {ud.get('plan')} {ud.get('unit')}",
        f"Факт: {ud.get('fact')} {ud.get('unit')}",
        f"Рабочих: {ud.get('workers')}",
        f"Техника: {', '.join(ud.get('equip_types', [])) or '—'}",
        f"Кол-во техники: {ud.get('equip_count') or '—'}",
    ]

    if ud.get("weather"):
        text_lines.append(f"Погода: {ud.get('weather')}")

    text_lines.extend(
        [
            f"Ответственный: {ud.get('responsible')}",
            f"Комментарий: {ud.get('comment') or '—'}",
            "",
            "Сохранить запись в ЖПР?",
        ]
    )

    await update.message.reply_text(
        "\n".join(text_lines),
        reply_markup=ReplyKeyboardMarkup(
            [[BTN_SAVE, BTN_FIX], [BTN_CANCEL]],
            resize_keyboard=True,
        ),
    )

    return ZHPR_REVIEW


async def st_review(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Финальное окно:
    - ✅ Сохранить
    - ✏️ Исправить (пока нет полноценного редактирования)
    - ❌ Отмена
    """
    txt = (update.message.text or "").strip()

    # Отмена
    if txt == BTN_CANCEL:
        context.user_data.pop("zhpr", None)
        context.user_data.pop("zhpr_struct", None)

        await update.message.reply_text(
            "Ок, запись ЖПР не сохранена.",
            reply_markup=main_menu(),
        )
        return ConversationHandler.END

    # Исправить (пока просто сбрасываем и предлагаем начать заново)
    if txt == BTN_FIX:
        context.user_data.pop("zhpr", None)
        context.user_data.pop("zhpr_struct", None)

        await update.message.reply_text(
            "Пока исправление полей не реализовано.\n"
            "Можно начать запись заново.",
            reply_markup=main_menu(),
        )
        return ConversationHandler.END

    # Сохранить
    if txt == BTN_SAVE:
        current = context.user_data.get("zhpr") or {}

        # Сохраняем шаблон для "Ещё вид работ (этот же участок)"
        template = deepcopy(current)
        for k in ("plan", "fact", "worktypes", "comment", "zhpr_id"):
            template.pop(k, None)

        context.user_data["zhpr_template"] = template

        ok, info = await create_notion_page_from_context(context)

        if ok:
            await update.message.reply_text(
                f"✅ Запись ЖПР сохранена в Notion.\nID: {info}",
                reply_markup=ReplyKeyboardMarkup(
                    [
                        [BTN_ADD_SAME],
                        [BTN_NEW_ENTRY],
                    ],
                    resize_keyboard=True,
                ),
            )
        else:
            await update.message.reply_text(
                f"⚠️ Не удалось сохранить запись ЖПР: {info}",
                reply_markup=ReplyKeyboardMarkup(
                    [[BTN_NEW_ENTRY]],
                    resize_keyboard=True,
                ),
            )

        context.user_data.pop("zhpr", None)
        context.user_data.pop("zhpr_struct", None)

        return ConversationHandler.END

    # Любой другой текст
    await update.message.reply_text(
        "Выбери одну из кнопок: сохранить, исправить или отменить."
    )
    return ZHPR_REVIEW


async def btn_add_same_entry(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Создание новой записи ЖПР на том же участке, что и последняя сохранённая.

    Использует zhpr_template:
    - та же дата
    - тот же раздел
    - тот же участок
    - те же рабочие, техника, погода, ответственный

    Прораб вводит ТОЛЬКО:
    - вид работ
    - объёмы
    - ед. измерения
    - комментарий (по желанию)
    """
    template = context.user_data.get("zhpr_template")
    if not template:
        # Если шаблона нет — ведём как обычную новую запись
        from zhpr_bot.dialog.date_step import btn_new_entry
        return await btn_new_entry(update, context)

    ud = deepcopy(template)
    context.user_data["zhpr"] = ud

    date_obj: datetime = ud.get("date_obj", datetime.now())

    msg_lines = [
        "Создаём ещё одну запись ЖПР на том же участке:",
        "",
        f"Дата: {date_obj.strftime('%d.%m.%Y')}",
        f"Раздел: {ud.get('section')}",
        f"Участок: {ud.get('subsection')}",
        f"Рабочих: {ud.get('workers')}",
        f"Техника: {', '.join(ud.get('equip_types', [])) or '—'}",
        f"Кол-во техники: {ud.get('equip_count') or '—'}",
    ]

    if ud.get("weather"):
        msg_lines.append(f"Погода: {ud.get('weather')}")

    msg_lines.append("")
    msg_lines.append(
        "Теперь введи *вид работ* для новой записи.\n"
        "Например: Бетон, Кирпич, Отделка.\n"
        "Если несколько — напиши через запятую (но в Notion запишется первый как основной)."
    )

    await update.message.reply_text(
        "\n".join(msg_lines),
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardRemove(),
    )

    return ZHPR_WORKTYPE
