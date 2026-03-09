# -*- coding: utf-8 -*-
"""
keyboards.py — клавиатуры Telegram для ЖПР-бота INTELLECTUM
"""

from telegram import ReplyKeyboardMarkup
from typing import List

from zhpr_bot.constants import (
    BTN_NEW_ENTRY,
)


def main_menu() -> ReplyKeyboardMarkup:
    """Главное меню бота."""
    return ReplyKeyboardMarkup(
        [[BTN_NEW_ENTRY]],
        resize_keyboard=True
    )


def chunk_buttons(items: List[str], per_row: int = 2) -> List[List[str]]:
    """
    Разбивает список кнопок на строки по per_row элементов.
    
    Пример:
    ["A","B","C"] → [["A","B"], ["C"]]
    """
    rows: List[List[str]] = []
    row: List[str] = []

    for item in items:
        row.append(item)
        if len(row) == per_row:
            rows.append(row)
            row = []

    if row:
        rows.append(row)

    return rows
