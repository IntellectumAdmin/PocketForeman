# -*- coding: utf-8 -*-
"""
constants.py — Кнопки и состояния FSM ЖПР-бота INTELLECTUM
"""

# ===== Текст кнопок =====
BTN_NEW_ENTRY   = "➕ Новая запись ЖПР"
BTN_CANCEL      = "❌ Отмена"
BTN_SAVE        = "✅ Сохранить"
BTN_FIX         = "✏️ Исправить"
BTN_DATE_KEEP   = "✅ Оставить"
BTN_CHOOSE_HERE = "✅ Выбрать здесь"
BTN_BACK        = "⬅ Назад"

# Кнопка для быстрой записи ещё одного вида работ
BTN_ADD_SAME    = "➕ Ещё вид работ (этот же участок)"

# Иконка папки для разделов ГПР
FOLDER_ICON     = "📁 "

# ===== Состояния диалога ЖПР (FSM) =====
(
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
) = range(200, 212)

# Состояние небольшого диалога настройки погоды (/weather)
WEATHER_SETUP = 150

__all__ = [
    "BTN_NEW_ENTRY",
    "BTN_CANCEL",
    "BTN_SAVE",
    "BTN_FIX",
    "BTN_DATE_KEEP",
    "BTN_CHOOSE_HERE",
    "BTN_BACK",
    "BTN_ADD_SAME",
    "FOLDER_ICON",
    "ZHPR_DATE",
    "ZHPR_SECTION",
    "ZHPR_SUBSECTION",
    "ZHPR_WORKTYPE",
    "ZHPR_PLAN",
    "ZHPR_FACT",
    "ZHPR_UNIT",
    "ZHPR_WORKERS",
    "ZHPR_EQUIP_TYPE",
    "ZHPR_EQUIP_COUNT",
    "ZHPR_COMMENT",
    "ZHPR_REVIEW",
    "WEATHER_SETUP",
]
