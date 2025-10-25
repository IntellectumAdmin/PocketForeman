# Скрипт для структуры ГПР в INTELLECTUM
# Читает structure.txt, создаёт папки в OneDrive и зеркалит в Notion
# Для школы №65 или любого объекта

import requests
import json
from collections import defaultdict

# Функция для чтения structure.txt и создания дерева
def parse_structure(file_path):
    tree = defaultdict(dict)
    with open(file_path, 'r') as f:
        lines = f.readlines()
    current_path = []
    for line in lines:
        level = line.count('    ')  # Отступы для уровней (4 пробела)
        name = line.strip().rstrip('/')
        if level == len(current_path):
            current_path.append(name)
        else:
            current_path = current_path[:level]
            current_path.append(name)
        # Строим дерево
        if level == 0:
            tree[name] = {}
        elif level == 1:
            tree[current_path[0]][name] = {}
        elif level == 2:
            tree[current_path[0]][current_path[1]][name] = {}
        # Можно добавить больше уровней
    return tree

# Функция для создания папок в OneDrive (используй Microsoft Graph API)
def create_onedrive_folders(tree, root_folder_id, token):
    url = "https://graph.microsoft.com/v1.0/me/drive/items/{id}/children".format(id=root_folder_id)
    headers = {"Authorization": "Bearer {0}".format(token), "Content-Type": "application/json"}
    for folder, sub in tree.items():
        data = {"name": folder, "folder": {}, "@microsoft.graph.conflictBehavior": "rename"}
        response = requests.post(url, headers=headers, data=json.dumps(data))
        sub_id = response.json()["id"]
        create_onedrive_folders(sub, sub_id, token)  # Рекурсия для подуровней

# Функция для зеркала в Notion (API)
def create_notion_structure(tree, database_id, token):
    url = "https://api.notion.com/v1/pages"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json", "Notion-Version": "2022-06-28"}
    for folder, sub in tree.items():
        data = {
            "parent": {"database_id": database_id},
            "properties": {"Name": {"title": [{"text": {"content": folder}}]}}
        }
        response = requests.post(url, headers=headers, data=json.dumps(data))
        page_id = response.json()["id"]
        create_notion_structure(sub, page_id, token)  # Рекурсия

# Пример использования
structure_file = "structure.txt"  # Твой файл с ГПР
gpr_tree = parse_structure(structure_file)
print("Дерево ГПР:", json.dumps(gpr_tree, ensure_ascii=False, indent=2))

# XAI-трассировка
print("XAI-трассировка: Структура прочитана из structure.txt. Создано дерево для OneDrive/Notion. Источник: Grok 11.10.2025")

# Для OneDrive/Notion: Замени TOKEN и ID на реальные
# create_onedrive_folders(gpr_tree, "root_folder_id", "onedrive_token")
# create_notion_structure(gpr_tree, "notion_database_id", "notion_token")