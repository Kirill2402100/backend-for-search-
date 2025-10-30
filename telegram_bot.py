# telegram_bot.py
from __future__ import annotations

from typing import Dict, Any, List, Optional
import imaplib
import email
import requests
import logging

from config import settings
from clickup_client import (
    clickup_client,
    READY_STATUS,
    SENT_STATUS,
    REPLIED_STATUS,
    NEW_STATUS,
)
from leads import upsert_leads_for_state
from send import run_send

log = logging.getLogger("tg-bot")

# ---------------------------------------------------------------------
# Константы
# ---------------------------------------------------------------------
TELEGRAM_API_BASE = "https://api.telegram.org/bot{token}"

US_STATES = [
    "AL","AK","AZ","AR","CA","CO","CT","DE","FL","GA",
    "HI","ID","IL","IN","IA","KS","KY","LA","ME","MD",
    "MA","MI","MN","MS","MO","MT","NE","NV","NH","NJ",
    "NM","NY","NC","ND","OH","OK","OR","PA","RI","SC",
    "SD","TN","TX","UT","VT","VA","WA","WV","WI","WY",
]

# на время жизни процесса помним, какой штат выбрал этот чат
USER_STATE: Dict[int, str] = {}


# ---------------------------------------------------------------------
# Вспомогалки по Telegram
# ---------------------------------------------------------------------
def _tg_send(
    chat_id: int,
    text: str,
    reply_markup: Optional[Dict[str, Any]] = None,
    parse_mode: str = "HTML",
) -> None:
    """
    Шлём напрямую в Telegram, чтобы не зависеть от telegram_notifier
    и не ловить ошибок типа "unexpected keyword argument".
    """
    token = settings.TELEGRAM_BOT_TOKEN
    if not token:
        log.warning("TELEGRAM_BOT_TOKEN is empty, message is lost: %s", text)
        return
    url = TELEGRAM_API_BASE.format(token=token) + "/sendMessage"
    payload: Dict[str, Any] = {
        "chat_id": chat_id,
        "text": text,
    }
    if parse_mode:
        payload["parse_mode"] = parse_mode
    if reply_markup:
        payload["reply_markup"] = reply_markup
    try:
        r = requests.post(url, json=payload, timeout=15)
        if r.status_code >= 300:
            log.warning("tg sendMessage failed: %s %s", r.status_code, r.text[:200])
    except Exception as e:
        log.warning("tg sendMessage error: %s", e)


def _allowed_chat(chat_id: int) -> bool:
    """
    Если указан TELEGRAM_CHAT_ID — отвечаем только ему.
    Если пусто — всем.
    """
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
    return [p for p in text.strip().split() if p.strip()]


# ---------------------------------------------------------------------
# Статистика по листу
# ---------------------------------------------------------------------
def _stats_for_state(state: str) -> str:
    list_id = clickup_client.get_or_create_list_for_state(state)
    tasks = clickup_client.get_leads_from_list(list_id)

    total = len(tasks)
    new_cnt = sum(1 for t in tasks if (t.get("status") or "").upper() == NEW_STATUS)
    ready = sum(1 for t in tasks if (t.get("status") or "").upper() == READY_STATUS)
    sent = sum(1 for t in tasks if (t.get("status") or "").upper() == SENT_STATUS)
    # email мы пока пишем в description, поэтому считаем "готовы" = READY
    remain = total - sent

    return (
        f"<b>Статистика {state}</b>\n"
        f"Всего в листе: {total}\n"
        f"NEW: {new_cnt}\n"
        f"Готовы к отправке: {ready}\n"
        f"Отправлено: {sent}\n"
        f"Осталось (не отправлено): {remain}"
    )


# ---------------------------------------------------------------------
# Сбор
# ---------------------------------------------------------------------
def _handle_collect(chat_id: int, state: str) -> None:
    # 1. гарантируем лист
    list_id = clickup_client.get_or_create_list_for_state(state)
    _tg_send(chat_id, f"Начинаю сбор по <b>{state}</b>... (list_id={list_id})")

    # 2. запускаем сбор (гугл -> ClickUp)
    report = upsert_leads_for_state(state)

    # 3. итогом — отчёт + актуальная статистика
    stats = _stats_for_state(state)
    text = (
        f"Сбор завершён: <b>{state}</b>\n"
        f"Найдено: {report['found']}\n"
        f"Создано новых: {report['created']}\n"
        f"Пропущено (дубликаты/ошибки): {report['skipped']}\n\n"
        f"{stats}"
    )
    _tg_send(chat_id, text)


# ---------------------------------------------------------------------
# Отправка писем
# ---------------------------------------------------------------------
def _handle_send(chat_id: int, state: str, limit: int) -> None:
    # run_send уже оперирует по state и листу
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
    _tg_send(chat_id, text)


# ---------------------------------------------------------------------
# Обработка ответных писем
# ---------------------------------------------------------------------
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
        # помечаем как прочитанное
        M.store(msg_id, "+FLAGS", "\\Seen")
    M.logout()
    return out


def _handle_replies(chat_id: int) -> None:
    from_list = _imap_fetch_unseen_froms()
    if not from_list:
        _tg_send(chat_id, "Новых ответов нет.")
        return

    moved = 0
    for addr in from_list:
        task = clickup_client.find_task_by_email(addr)
        if task:
            clickup_client.move_lead_to_status(task["task_id"], REPLIED_STATUS)
            moved += 1
            _tg_send(
                chat_id,
                f"Ответ от <b>{task['clinic_name']}</b> ({addr}). Перенесено в «{REPLIED_STATUS}».",
            )
    if moved == 0:
        _tg_send(chat_id, "Ответы есть, но задачи по ним не нашлись.")


# ---------------------------------------------------------------------
# help
# ---------------------------------------------------------------------
def _help_text() -> str:
    return (
        "Команды:\n"
        "/menu — клавиатура штатов\n"
        "/collect NY — создать лист и собрать клиники по штату (алиас: /search NY)\n"
        "/send NY 10 — отправить письма (или /send 10 если штат уже выбран)\n"
        "/stats NY — сводка по штату\n"
        "/replies — разобрать входящие ответы\n"
        "/id — показать chat id"
    )


# ---------------------------------------------------------------------
# Главный обработчик
# ---------------------------------------------------------------------
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

    # выбор штата кнопкой
    if text.upper() in US_STATES:
        USER_STATE[chat_id] = text.upper()
        _tg_send(chat_id, f"Штат выбран: <b>{text.upper()}</b>")
        return {"ok": True}

    parts = _parse_cmd(text)
    if not parts:
        return {"ok": True}

    cmd = parts[0].lower()

    if cmd in ("/start", "/help"):
        _tg_send(chat_id, _help_text(), parse_mode=None)
        return {"ok": True}

    if cmd == "/id":
        _tg_send(chat_id, f"Ваш chat id: <code>{chat_id}</code>")
        return {"ok": True}

    if cmd == "/menu":
        _tg_send(chat_id, "Выбери штат, затем используй /collect, /send, /stats", reply_markup=_states_keyboard())
        return {"ok": True}

    if cmd in ("/collect", "/search"):
        state = (parts[1].upper() if len(parts) > 1 else USER_STATE.get(chat_id))
        if not state or state not in US_STATES:
            _tg_send(chat_id, "Укажи штат: /collect NY или выбери через /menu", parse_mode=None)
            return {"ok": True}
        _handle_collect(chat_id, state)
        return {"ok": True}

    if cmd == "/send":
        # /send NY 10 или /send 10 (если штат уже выбран)
        if len(parts) == 3:
            state = parts[1].upper()
            lim = int(parts[2])
        else:
            state = USER_STATE.get(chat_id)
            if not state:
                _tg_send(chat_id, "Сначала укажи штат: /send NY 10 или выбери через /menu", parse_mode=None)
                return {"ok": True}
            lim = int(parts[1]) if len(parts) > 1 else 50
        _handle_send(chat_id, state, lim)
        return {"ok": True}

    if cmd == "/stats":
        state = (parts[1].upper() if len(parts) > 1 else USER_STATE.get(chat_id))
        if not state or state not in US_STATES:
            _tg_send(chat_id, "Укажи штат: /stats NY или выбери через /menu", parse_mode=None)
            return {"ok": True}
        _tg_send(chat_id, _stats_for_state(state))
        return {"ok": True}

    if cmd == "/replies":
        _handle_replies(chat_id)
        return {"ok": True}

    # по умолчанию
    _tg_send(chat_id, "Не понимаю команду. Напиши /help", parse_mode=None)
    return {"ok": True}
