# -*- coding: utf-8 -*-
"""
weather_service.py — работа с погодой для ЖПР-бота INTELLECTUM

Здесь:
- хранение города/координат пользователя в weather_store.json
- запрос к OpenWeather
"""

import json
import logging
import os
from typing import Dict, Any, Optional

import requests

from zhpr_bot.config import (
    OPENWEATHER_API_KEY,
    WEATHER_STORE_FILE,
)

log = logging.getLogger(__name__)


# ===== Хранилище города/координат пользователя =====

def _load_weather_store() -> Dict[str, Any]:
    """Читает weather_store.json (если нет — возвращает пустой словарь)."""
    if not os.path.exists(WEATHER_STORE_FILE):
        return {}

    try:
        with open(WEATHER_STORE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        log.exception("Не удалось прочитать weather_store.json")
        return {}


def _save_weather_store(data: Dict[str, Any]) -> None:
    """Сохраняет словарь в weather_store.json."""
    try:
        with open(WEATHER_STORE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        log.exception("Не удалось сохранить weather_store.json")


def get_user_location(user_id: int) -> Optional[str]:
    """Получить сохранённый город/координаты пользователя по user_id."""
    data = _load_weather_store()
    return data.get(str(user_id))


def set_user_location(user_id: int, value: Optional[str]) -> None:
    """
    Сохранить город/координаты пользователя.
    Если value пустое — удаляем запись.
    """
    data = _load_weather_store()
    key = str(user_id)

    if value:
        data[key] = value
    elif key in data:
        data.pop(key)

    _save_weather_store(data)


# ===== Запрос к OpenWeather =====

def fetch_weather_text(location: str) -> Optional[str]:
    """
    Получить погоду строкой вида:
    'Уральск, 7.0°C, Небольшая морось'

    location: 'Уральск' или '51.233, 51.383'
    """
    if not OPENWEATHER_API_KEY:
        return None

    params: Dict[str, Any] = {
        "appid": OPENWEATHER_API_KEY,
        "units": "metric",
        "lang": "ru",
    }

    loc = location.strip()

    # Координаты через запятую
    if "," in loc and any(ch.isdigit() for ch in loc):
        try:
            lat_str, lon_str = [x.strip() for x in loc.split(",", 1)]
            params["lat"] = float(lat_str.replace(" ", ""))
            params["lon"] = float(lon_str.replace(" ", ""))
        except Exception:
            log.warning("Не смог распарсить координаты погоды: %r", loc)
            params["q"] = loc
    else:
        params["q"] = loc

    try:
        r = requests.get(
            "https://api.openweathermap.org/data/2.5/weather",
            params=params,
            timeout=10,
        )
    except Exception:
        log.exception("Ошибка запроса к OpenWeather")
        return None

    if r.status_code != 200:
        log.warning("OpenWeather вернул %s: %s", r.status_code, r.text)
        return None

    try:
        j = r.json()
        temp = j.get("main", {}).get("temp")
        weather_list = j.get("weather", [])
        desc = weather_list[0].get("description") if weather_list else ""
        city_name = j.get("name") or loc

        if temp is None:
            return None

        desc_norm = (desc or "").capitalize()
        return f"{city_name}, {temp:.1f}°C, {desc_norm}"
    except Exception:
        log.exception("Не удалось распарсить ответ OpenWeather")
        return None
