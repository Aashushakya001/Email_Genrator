# import json
# import os
# from typing import List, Dict

# MEMORY_PATH = os.path.join("app", "data", "chat_memory.json")

# def ensure_memory_path():
#     d = os.path.dirname(MEMORY_PATH)
#     os.makedirs(d, exist_ok=True)
#     if not os.path.exists(MEMORY_PATH):
#         with open(MEMORY_PATH, "w", encoding="utf-8") as f:
#             json.dump([], f)

# def load_memory() -> List[Dict]:
#     ensure_memory_path()
#     with open(MEMORY_PATH, "r", encoding="utf-8") as f:
#         return json.load(f)

# def append_message(role: str, content: str):
#     mem = load_memory()
#     mem.append({"role": role, "content": content})
#     with open(MEMORY_PATH, "w", encoding="utf-8") as f:
#         json.dump(mem, f, indent=2)

# def clear_memory():
#     ensure_memory_path()
#     with open(MEMORY_PATH, "w", encoding="utf-8") as f:
#         json.dump([], f)



# ##########################
"""
chat_memory.py — Persistent chat memory with per-email refinement thread.

Two separate stores:
  1. chat_memory.json   — global assistant history
  2. email_thread.json  — email refinement conversation (reset per generated email)
"""

from __future__ import annotations

import json
import os
from typing import Dict, List

_DATA_DIR = os.path.join("app", "data")
MEMORY_PATH = os.path.join(_DATA_DIR, "chat_memory.json")
EMAIL_THREAD_PATH = os.path.join(_DATA_DIR, "email_thread.json")


def _ensure(path: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as fh:
            json.dump([], fh)


def _read(path: str) -> List[Dict]:
    _ensure(path)
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
            return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def _write(path: str, messages: List[Dict]) -> None:
    _ensure(path)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(messages, fh, indent=2, ensure_ascii=False)


# ── Global memory ─────────────────────────────────────────────────────────────

def load_memory() -> List[Dict]:
    return _read(MEMORY_PATH)


def append_message(role: str, content: str) -> None:
    mem = _read(MEMORY_PATH)
    mem.append({"role": role, "content": content})
    _write(MEMORY_PATH, mem)


def clear_memory() -> None:
    _write(MEMORY_PATH, [])


# ── Email refinement thread ───────────────────────────────────────────────────

def load_email_thread() -> List[Dict]:
    return _read(EMAIL_THREAD_PATH)


def start_email_thread(job: Dict, resume_info: Dict, initial_email: str) -> None:
    """Reset the thread and seed it with system context + the initial email."""
    system_ctx = (
        "You are an expert job application email writer with access to the "
        "candidate's full resume and the job description below.\n\n"
        "Rules:\n"
        "1. ONLY use contact details (name, email, phone, LinkedIn, GitHub) "
        "that are explicitly present in RESUME_JSON. NEVER invent or guess values.\n"
        "2. ONLY use the company name from JOB_JSON. NEVER invent a company name.\n"
        "3. If a value (e.g. LinkedIn) is missing from RESUME_JSON, omit that line entirely.\n"
        "4. When the user asks for changes, output the COMPLETE rewritten email "
        "(Subject + body) — never just a partial diff.\n\n"
        f"JOB_JSON:\n{json.dumps(job, ensure_ascii=False)}\n\n"
        f"RESUME_JSON:\n{json.dumps(resume_info, ensure_ascii=False)}"
    )
    _write(EMAIL_THREAD_PATH, [
        {"role": "system", "content": system_ctx},
        {"role": "assistant", "content": initial_email},
    ])


def append_email_thread(role: str, content: str) -> None:
    thread = _read(EMAIL_THREAD_PATH)
    thread.append({"role": role, "content": content})
    _write(EMAIL_THREAD_PATH, thread)


def clear_email_thread() -> None:
    _write(EMAIL_THREAD_PATH, [])