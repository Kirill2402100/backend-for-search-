# telegram_bot.py
from typing import Dict, Any, Optional, List
import imaplib
import email

from config import settings
from clickup_client import (
    clickup_client,
    READY_STATUS,
    SENT_STATUS,
    REPLIED_STATUS,
    NEW_STATUS,
)
from telegram_notifier import send_message as tg_send
from send import run_send
from leads import upsert_leads_for_state

TELEGRAM_API_BASE = "https://api.telegram.org"

US_STATES = [
    "AL","AK","AZ","AR","CA","CO","CT","DE","FL","GA",
    "HI","ID","IL","IN","IA","KS","KY","LA","ME","MD",
    "MA","MI","MN","MS","MO","MT","NE","NV","NH","NJ",
    "NM","NY","NC","ND","OH","OK","OR","PA","RI","SC",
    "SD","TN","TX","UT","VT","VA","WA","WV","WI","WY"
]

USER_STATE: Dict[int, str] = {}


def _allowed_chat(chat_id: int) -> bool:
    want = str(getattr(settings, "TELEGRAM_CHAT_ID", "")).strip()
    return (not want) or (str(chat_id) == want)


def _states_keyboard() -> Dict[str, Any]:
    rows: List[List[Dict[str, str]]] = []
    row: List[Dict[str, str]] = []
    for i, s in enumerate(US_STATES, start=1):
        row.append({"text": s})
        if i % 5 == 0:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return {"keyboard": rows, "resize_keyboard": True, "one_time_keyboard": False}


def _parse_cmd(text: str) -> List[str]:
    parts = text.strip().split()
    return [p.strip() for p in parts if p.strip()]


def _task_status_str(task: Dict[str, Any]) -> str:
    """
    ClickUp иногда возвращает 'status': 'open', а иногда 'status': {'status': 'open', ...}
    """
    st = task.get("status")
    if isinstance(st, str):
        return st
    if isinstance(st, dict):
        return st.get("status") or st.get("value") or ""
    return ""


def _stats_for_state(state: str) -> str:
    list_id = clickup_client.get_or_create_list_for_state(state)
    tasks = clickup_client.get_leads_from_list(list_id)

    total = len(tasks)

    new_cnt = 0
    ready_cnt = 0
    sent_cnt = 0

    for t in tasks:
        st = _task_status_str(t).upper()
        if st == NEW_STATUS:
            new_cnt += 1
        elif st == READY_STATUS:
            ready_cnt += 1
        elif st == SENT_STATUS:
            sent_cnt += 1

    remain = total - sent_cnt

    return (
        f"Статистика {state}\n"
        f"Всего в листе: {total}\n"
        f"NEW: {new_cnt}\n"
        f"Готовы к отправке: {ready_cnt}\n"
        f"Отправлено: {sent_cnt}\n"
        f"Осталось (не отправлено): {remain}"
    )


def _handle_collect(chat_id: int, state: str) -> None:
    # собираем
    report = upsert_leads_for_state(state)

    # после сбора ещё раз считаем по факту
    stats = _stats_for_state(state)

    text = (
        f"Сбор завершён: {state}\n"
        f"Найдено: {report['found']}\n"
        f"Создано новых: {report['created']}\n"
        f"Пропущено (дубликаты/ошибки): {report['skipped']}\n\n"
        f"{stats}"
    )
    tg_send(chat_id, text)


def _handle_send(chat_id: int, state: str, limit: int) -> None:
    report = run_send(state=state, limit=limit)
    text = (
        f"<b>Рассылка {state}</b>\n"
        f"Отправлено: {report['sent']}\n"
        f"Невалидных: {report['invalid']}\n"
        f"Без email: {report['skipped_no_email']}\n"
        f"Ошибок отправки: {report['failed_send']}\n"
        f"Осталось (с email, не отправлено): {report['remaining_unsent']}\n"
        f"Всего в листе: {report['total_in_list']}"
    )
    tg_send(chat_id, text, parse_mode="HTML")


def _imap_fetch_unseen_froms(n_last: int = 50) -> List[str]:
    host = getattr(settings, "SMTP_HOST", "mail.adm.tools")
    username = settings.SMTP_USERNAME
    password = settings.SMTP_PASSWORD

    out: List[str] = []
    M = imaplib.IMAP4_SSL(host, 993)
    M.login(username, password)
    M.select("INBOX")
    status, data = M.search(None, "UNSEEN")
    if status != "OK":
        M.logout()
        return out

    ids = data[0].split()[-n_last:]
    for msg_id in ids:
        typ, msg_data = M.fetch(msg_id, "(RFC822)")
        if typ != "OK":
            continue
        msg = email.message_from_bytes(msg_data[0][1])
        from_hdr = email.utils.parseaddr(msg.get("From"))[1]
        out.append(from_hdr)
        M.store(msg_id, "+FLAGS", "\\Seen")
    M.logout()
    return out


def _handle_replies(chat_id: int) -> None:
    from_list = _imap_fetch_unseen_froms()
    if not from_list:
        tg_send(chat_id, "Новых ответов нет.")
        return

    moved = 0
    for addr in from_list:
        task = clickup_client.find_task_by_email(addr)
        if task:
            clickup_client.move_lead_to_status(task["task_id"], REPLIED_STATUS)
            moved += 1
            tg_send(
                chat_id,
                f"Ответ от <b>{task['clinic_name']}</b> ({addr}). Перенесено в «{REPLIED_STATUS}».",
                parse_mode="HTML",
            )
    if moved == 0:
        tg_send(chat_id, "Ответы получены, но соответствующие задачи не найдены.")


def _help_text() -> str:
    return (
        "Команды:\n"
        "/menu — клавиатура штатов\n"
        "/collect NY — собрать и показать статистику\n"
        "/send NY 10 — отправить письма (limit) или /send 10 (если штат выбран)\n"
        "/stats NY — сводка по штату\n"
        "/replies — обработать входящие ответы\n"
        "/id — показать ваш chat id"
    )


def register_commands() -> None:
    token = settings.TELEGRAM_BOT_TOKEN
    if not token:
        return
    try:
        import requests
        commands = [
            {"command": "menu",    "description": "Клавиатура штатов"},
            {"command": "help",    "description": "Справка по командам"},
            {"command": "id",      "description": "Показать мой chat id"},
            {"command": "collect", "description": "Создать лист и сводку по штату"},
            {"command": "search",  "description": "Алиас для /collect"},
            {"command": "send",    "description": "Отправить письма"},
            {"command": "stats",   "description": "Статистика по штату"},
            {"command": "replies", "description": "Обработать входящие ответы"},
        ]
        r = requests.post(
            f"{TELEGRAM_API_BASE}/bot{token}/setMyCommands",
            json={"commands": commands},
            timeout=10,
        )
        print(f"[tg] setMyCommands: {r.status_code} {r.text[:200]}")
    except Exception as e:
        print(f"[tg] setMyCommands error: {e}")


def handle_update(update: Dict[str, Any]) -> Dict[str, Any]:
    msg = update.get("message") or update.get("edited_message")
    if not msg:
        return {"ok": True}

    chat_id = msg.get("chat", {}).get("id")
    text = (msg.get("text") or "").strip()

    if not chat_id or not text:
        return {"ok": True}
    if not _allowed_chat(chat_id):
        return {"ok": True}

    if text.upper() in US_STATES:
        USER_STATE[chat_id] = text.upper()
        tg_send(chat_id, f"Штат выбран: <b>{text.upper()}</b>", parse_mode="HTML")
        return {"ok": True}

    parts = _parse_cmd(text)
    if not parts:
        return {"ok": True}

    cmd = parts[0].lower()

    if cmd in ("/start", "/help"):
        tg_send(chat_id, _help_text())
        return {"ok": True}

    if cmd == "/id":
        tg_send(chat_id, f"Ваш chat id: <code>{chat_id}</code>", parse_mode="HTML")
        return {"ok": True}

    if cmd == "/menu":
        tg_send(chat_id, "Выбери штат, затем используй /collect, /send, /stats", reply_markup=_states_keyboard())
        return {"ok": True}

    if cmd in ("/collect", "/search"):
        state = (parts[1].upper() if len(parts) > 1 else USER_STATE.get(chat_id))
        if not state or state not in US_STATES:
            tg_send(chat_id, "Укажи штат: /collect NY или выбери через /menu")
            return {"ok": True}
        _handle_collect(chat_id, state)
        return {"ok": True}

    if cmd == "/send":
        if len(parts) == 3:
            state = parts[1].upper()
            lim = int(parts[2])
        else:
            state = USER_STATE.get(chat_id)
            if not state:
                tg_send(chat_id, "Сначала укажи штат: /send NY 1 или выбери через /menu")
                return {"ok": True}
            lim = int(parts[1]) if len(parts) > 1 else 50
        _handle_send(chat_id, state, lim)
        return {"ok": True}

    if cmd == "/stats":
        state = (parts[1].upper() if len(parts) > 1 else USER_STATE.get(chat_id))
        if not state or state not in US_STATES:
            tg_send(chat_id, "Укажи штат: /stats NY или выбери через /menu")
            return {"ok": True}
        tg_send(chat_id, _stats_for_state(state))
        return {"ok": True}

    if cmd == "/replies":
        _handle_replies(chat_id)
        return {"ok": True}

    tg_send(chat_id, "Не понимаю команду. Напиши /help")
    return {"ok": True}
