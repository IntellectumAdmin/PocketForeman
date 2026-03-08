# -*- coding: utf-8 -*-
"""
section_tree.py — дерево разделов ГПР для ЖПР-бота INTELLECTUM

Парсим файл structure.txt с отступами и строим иерархию SectionNode.
"""

import logging
import os
from typing import List, Tuple, Dict, Any

from zhpr_bot.config import STRUCTURE_FILE

log = logging.getLogger(__name__)


class SectionNode:
    """Узел дерева разделов ГПР."""

    def __init__(self, name: str):
        self.name: str = name
        self.children: List["SectionNode"] = []

    def __repr__(self) -> str:
        return f"SectionNode({self.name!r}, children={len(self.children)})"


def load_structure_tree(path: str) -> List[SectionNode]:
    """
    Парсим structure.txt с отступами пробелами (шаг 4 пробела).

    Пример:
        Школа_65
            1. Земляные работы
                1.1. Котлованы
                1.2. Обратная засыпка
            2. Фундаменты
    """
    if not os.path.exists(path):
        log.warning("structure.txt не найден: %s", path)
        return []

    roots: List[SectionNode] = []
    stack: List[Tuple[int, SectionNode]] = []

    with open(path, "r", encoding="utf-8") as f:
        for raw in f:
            line = raw.rstrip()
            if not line:
                continue

            indent = len(line) - len(line.lstrip(" "))
            name = line.strip().rstrip("/")

            node = SectionNode(name)

            if not stack:
                roots.append(node)
                stack.append((indent, node))
                continue

            while stack and stack[-1][0] >= indent:
                stack.pop()

            if not stack:
                roots.append(node)
                stack.append((indent, node))
            else:
                parent = stack[-1][1]
                parent.children.append(node)
                stack.append((indent, node))

    log.info("structure.txt загружен, корневых разделов: %d", len(roots))
    return roots


# Глобальное дерево, загружаем один раз при импорте модуля
STRUCTURE_ROOTS: List[SectionNode] = load_structure_tree(STRUCTURE_FILE)


def get_current_children(struct_ctx: Dict[str, Any]) -> List[SectionNode]:
    """
    Возвращает список дочерних разделов для текущего уровня навигации.

    struct_ctx:
        {
            "path":  [строка, ...],
            "stack": [SectionNode, ...],
        }
    """
    stack: List[SectionNode] = struct_ctx.get("stack", [])
    if not stack:
        return STRUCTURE_ROOTS
    return stack[-1].children
