# -*- coding: utf-8 -*-
"""
Синхронизация структуры ГПР из structure.txt в Cloudinary.
- читает STRUCTURE_FILE
- строит список путей (a/b/c)
- создаёт папки в Cloudinary под CLOUD_ROOT
- сохраняет кэш structure_cache.json (для бота)

Запуск вручную:
    python structure_sync.py
Или бот вызовет это через /sync.
"""

import os
import json
from typing import List, Dict

from dotenv import load_dotenv
import cloudinary
import cloudinary.api

load_dotenv()

CLOUD_NAME = os.getenv("CLOUD_NAME", "")
CLOUD_API_KEY = os.getenv("CLOUD_API_KEY", "")
CLOUD_API_SECRET = os.getenv("CLOUD_API_SECRET", "")

CLOUD_ROOT = os.getenv("CLOUD_ROOT", "Project")
STRUCTURE_FILE = os.getenv("STRUCTURE_FILE", "structure.txt")
CACHE_PATH = "structure_cache.json"


def _config_cloudinary():
    if not (CLOUD_NAME and CLOUD_API_KEY and CLOUD_API_SECRET):
        raise RuntimeError("Не заданы CLOUD_NAME/CLOUD_API_KEY/CLOUD_API_SECRET в .env")
    cloudinary.config(
        cloud_name=CLOUD_NAME,
        api_key=CLOUD_API_KEY,
        api_secret=CLOUD_API_SECRET,
        secure=True,
    )


def _parse_structure_txt(path: str) -> List[str]:
    """
    Преобразует structure.txt (с отступами 2 пробела) в список путей.
    Пример:
      Здание школы/
        Архитектурная часть/
          Фасады/
    -> ["Здание школы/Архитектурная часть/Фасады"]
    """
    if not os.path.exists(path):
        raise FileNotFoundError(f"Нет файла структуры: {path}")

    with open(path, "r", encoding="utf-8") as f:
        lines = [ln.rstrip() for ln in f.readlines()]

    paths: List[str] = []
    stack: List[str] = []

    for ln in lines:
        if not ln.strip():
            continue
        # уровень по "  " (2 пробела)
        raw = ln.rstrip("/")
        level = 0
        while raw.startswith("  " * (level + 1)):
            level += 1
        name = raw.strip()
        # убираем ведущие отступы
        name = name.replace("  " * level, "", 1)
        name = name.strip("/").strip()

        # усечь стек до текущего уровня и добавить элемент
        stack = stack[:level] + [name]
        # если следующая строка скорее вложение — ещё не путь,
        # но нам удобно добавлять все уровни как допустимые "папки-загрузки"
        paths.append("/".join(stack))

    # уникализируем, чтобы не плодить дубликаты
    uniq = []
    seen = set()
    for p in paths:
        if p not in seen:
            uniq.append(p)
            seen.add(p)
    return uniq


def _ensure_folders_in_cloudinary(paths: List[str], root: str) -> None:
    """
    Создаёт папки в Cloudinary (они создаются лениво при upload,
    но явное создание удобнее для контроля).
    """
    for p in paths:
        folder = f"{root}/{p}" if root else p
        try:
            cloudinary.api.create_folder(folder)
            print(f"✓ Создана папка: {folder}")
        except cloudinary.exceptions.Error as e:
            # Если уже существует — Cloudinary вернёт ошибку уровня предупреждения,
            # её можно просто игнорировать
            msg = str(e)
            if "already exists" in msg or "exists" in msg:
                print(f"= Уже есть: {folder}")
            else:
                print(f"! Ошибка при создании {folder}: {msg}")


def _save_cache(paths: List[str], cache_path: str, root: str) -> None:
    data = {
        "root": root,
        "paths": paths,
    }
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"✓ Кэш путей сохранён: {cache_path} (root={root}, {len(paths)} путей)")


def sync_structure() -> Dict[str, object]:
    _config_cloudinary()
    paths = _parse_structure_txt(STRUCTURE_FILE)
    _ensure_folders_in_cloudinary(paths, CLOUD_ROOT)
    _save_cache(paths, CACHE_PATH, CLOUD_ROOT)
    return {"root": CLOUD_ROOT, "paths": paths}


if __name__ == "__main__":
    print("=== Синхронизация структуры Cloudinary из structure.txt ===")
    info = sync_structure()
    print(f"Готово. Путей: {len(info['paths'])}, root: {info['root']}")
