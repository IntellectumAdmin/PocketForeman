# -*- coding: utf-8 -*-
"""
section_step.py — выбор раздела ГПР по дереву structure.txt
"""

from typing import List, Dict, Any

from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import ContextTypes

from zhpr_bot.constants import (
    ZHPR_SECTION,
    ZHPR_SUBSECTION,
    BTN_BACK,
    BTN_CHOOSE_HERE,
    FOLDER_ICON,
)
from zhpr_bot.utils.keyboards import chunk_buttons
from zhpr_bot.structure.section_tree import get_current_children, SectionNode


async def _send_section_level(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Показываем текущий уровень дерева разделов в виде кнопок.
    """
    struct_ctx: Dict[str, Any] = context.user_data.setdefault("zhpr_struct", {})
    path: List[str] = struct_ctx.get("path", [])
    children: List[SectionNode] = get_current_children(struct_ctx)

    # Если больше нет дочерних разделов — считаем раздел выбранным
    if not children:
        section_full = " / ".join(path) if path else "—"
        context.user_data["zhpr"]["section"] = section_full
        context.user_data.pop("zhpr_struct", None)

        await update.message.reply_text(
            f"Раздел выбран: {section_full}\n\n"
            "Теперь введи *подраздел / участок*.\n"
            "Например: Цоколь / входная группа",
            parse_mode="Markdown",
            reply_markup=ReplyKeyboardRemove(),
        )
        return ZHPR_SUBSECTION

    # Формируем текст заголовка
    if not path:
        header = "Выбери раздел проекта (корень: Школа_65):"
    else:
        header = f"Раздел: {' / '.join(path)}\nВыбери подраздел:"

    # Список кнопок-папок
    btns = [FOLDER_ICON + n.name for n in children]
    keyboard = chunk_buttons(btns, per_row=2)

    if path:
        keyboard.append([BTN_BACK, BTN_CHOOSE_HERE])
    else:
        keyboard.append([BTN_CHOOSE_HERE])

    await update.message.reply_text(
        header,
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True),
    )
    return ZHPR_SECTION


async def start_section_selection(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    """
    Инициализация структуры для навигации по разделам и первый показ меню.
    """
    struct_ctx = {
        "path": [],
        "stack": [],
    }
    context.user_data["zhpr_struct"] = struct_ctx
    return await _send_section_level(update, context)


async def st_section(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    Обработка выбора раздела/подраздела:
    - нажатие на папку
    - Назад
    - Выбрать здесь
    """
    txt = (update.message.text or "").strip()
    struct_ctx: Dict[str, Any] = context.user_data.setdefault("zhpr_struct", {})
    path: List[str] = struct_ctx.get("path", [])
    stack: List[SectionNode] = struct_ctx.get("stack", [])

    # Нажатие на папку
    if txt.startswith(FOLDER_ICON):
        name = txt[len(FOLDER_ICON):].strip()
        children = get_current_children(struct_ctx)
        target = next((n for n in children if n.name == name), None)

        if not target:
            await update.message.reply_text("Не нашёл такой раздел. Попробуй ещё раз.")
            return await _send_section_level(update, context)

        stack.append(target)
        path.append(target.name)

        struct_ctx["stack"] = stack
        struct_ctx["path"] = path

        return await _send_section_level(update, context)

    # Кнопка Назад
    if txt == BTN_BACK:
        if stack:
            stack.pop()
        if path:
            path.pop()

        struct_ctx["stack"] = stack
        struct_ctx["path"] = path

        return await _send_section_level(update, context)

    # Кнопка "Выбрать здесь"
    if txt == BTN_CHOOSE_HERE:
        if not path:
            await update.message.reply_text(
                "Сначала выбери хотя бы один раздел (нажми на папку)."
            )
            return await _send_section_level(update, context)

        section_full = " / ".join(path)
        context.user_data["zhpr"]["section"] = section_full
        context.user_data.pop("zhpr_struct", None)

        await update.message.reply_text(
            f"Раздел выбран: {section_full}\n\n"
            "Теперь введи *подраздел / участок*.\n"
            "Например: Цоколь / входная группа",
            parse_mode="Markdown",
            reply_markup=ReplyKeyboardRemove(),
        )
        return ZHPR_SUBSECTION

    # Любой другой текст
    await update.message.reply_text(
        "Чтобы выбрать раздел, нажми на одну из кнопок-папок ниже."
    )
    return await _send_section_level(update, context)
