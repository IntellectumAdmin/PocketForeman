# -*- coding: utf-8 -*-
"""
Создаёт дерево папок в локальном OneDrive по структуре из structure.txt.
Отступ = 2 пробела на уровень, каждая папка заканчивается слешем /.
Корневая папка проекта: "Школа 65".
"""

import os
import sys

PROJECT_ROOT_NAME = "Школа 65"
STRUCTURE_FILE = "structure.txt"

def find_onedrive_root() -> str:
    """Пытается найти локальную папку OneDrive в Windows по переменной окружения."""
    env = os.environ
    for key in ("OneDrive", "OneDriveConsumer", "OneDriveCommercial"):
        p = env.get(key)
        if p and os.path.isdir(p):
            return p
    home = os.path.expanduser("~")
    candidates = [
        os.path.join(home, "OneDrive"),
        os.path.join(home, "OneDrive - Личное"),
        os.path.join(home, "OneDrive - Personal"),
    ]
    for p in candidates:
        if os.path.isdir(p):
            return p
    raise RuntimeError("Не найден локальный каталог OneDrive. Убедись, что OneDrive установлен и запущен.")

def iter_paths_from_structure(project_root: str, filename: str):
    """
    Возвращает абсолютные пути папок согласно structure.txt.
    ВАЖНО: теперь мы никогда не заменяем корень проекта,
    а строим список имен относительно корня.
    """
    with open(filename, "r", encoding="utf-8") as f:
        names_stack = []   # стек ИМЕН (без project_root)
        prev_level = 0

        for raw in f:
            line = raw.rstrip("\n")
            if not line.strip():
                continue
            if not line.endswith("/"):
                continue

            leading_spaces = len(line) - len(line.lstrip(" "))
            level = leading_spaces // 2
            name = line.strip().rstrip("/")

            if level > prev_level:
                names_stack.append(name)
            elif level == prev_level:
                if names_stack:
                    names_stack[-1] = name
                else:
                    names_stack.append(name)
            else:
                for _ in range(prev_level - level):
                    if names_stack:
                        names_stack.pop()
                if names_stack:
                    names_stack[-1] = name
                else:
                    names_stack.append(name)

            prev_level = level
            yield os.path.join(project_root, *names_stack)

def main():
    try:
        onedrive_root = find_onedrive_root()
    except Exception as e:
        print(f"✗ {e}")
        sys.exit(1)

    project_root = os.path.join(onedrive_root, PROJECT_ROOT_NAME)
    os.makedirs(project_root, exist_ok=True)
    print(f"✓ Корневая папка проекта: {project_root}")

    total = 0
    for path in iter_paths_from_structure(project_root, STRUCTURE_FILE):
        os.makedirs(path, exist_ok=True)
        total += 1
        if total % 50 == 0:
            print(f"... создано/проверено папок: {total}")

    print(f"✓ Готово. Всего обработано папок: {total}")
    print("Подожди немного — OneDrive сам синхронизирует структуру в облако.")

if __name__ == "__main__":
    main()
