import json
import os
from typing import List, Dict

MEMORY_PATH = os.path.join("app", "data", "chat_memory.json")

def ensure_memory_path():
    d = os.path.dirname(MEMORY_PATH)
    os.makedirs(d, exist_ok=True)
    if not os.path.exists(MEMORY_PATH):
        with open(MEMORY_PATH, "w", encoding="utf-8") as f:
            json.dump([], f)

def load_memory() -> List[Dict]:
    ensure_memory_path()
    with open(MEMORY_PATH, "r", encoding="utf-8") as f:
        return json.load(f)

def append_message(role: str, content: str):
    mem = load_memory()
    mem.append({"role": role, "content": content})
    with open(MEMORY_PATH, "w", encoding="utf-8") as f:
        json.dump(mem, f, indent=2)

def clear_memory():
    ensure_memory_path()
    with open(MEMORY_PATH, "w", encoding="utf-8") as f:
        json.dump([], f)
