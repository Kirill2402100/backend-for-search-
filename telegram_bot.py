# telegram_bot.py
from typing import Dict, Any, Optional, List
import imaplib
import email
import logging

from config import settings
from clickup_client import (
    clickup_client,
    READY_STATUS,
    SENT_STATUS,
    REPLIED_STATUS,
    NEW_STATUS,
    INVALID_STATUS # Добавим
)
from telegram_notifier import send_message as tg_send
from send import run_send # <-- Импортируем новый run_send
from leads import upsert_leads_for_state
from utils import _task_status_str # <-- 🟢 ИСПРАВЛЕНИЕ

log = logging.getLogger("telegram_bot")
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

#
# 🟢 Функция _task_status_str УДАЛЕНА ОТСЮДА и перенесена в utils.py 🟢
#

def _stats_for_state(state: str) -> str:
    try:
        list_id = clickup_client.get_or_create_list_for_state(state)
        tasks = clickup_client.get_leads_from_list(list_id)
    except Exception as e:
        log.error("Failed to get stats for %s: %s", state, e)
        return f"Ошибка получения статистики для {state}: {e}"

    total = len(tasks)
    new_cnt = 0
    ready_cnt = 0
    sent_cnt = 0
    replied_cnt = 0
    invalid_cnt = 0

    for t in tasks:
        st = _task_status_str(t).upper()
        if st == NEW_STATUS:
            new_cnt += 1
        elif st == READY_STATUS:
            ready_cnt += 1
        elif st == SENT_STATUS:
            sent_cnt += 1
        elif st == REPLIED_STATUS:
            replied_cnt += 1
        elif st == INVALID_STATUS:
            invalid_cnt += 1
            
    other_cnt = total - (new_cnt + ready_cnt + sent_cnt + replied_cnt + invalid_cnt)

    return (
        f"<b>Статистика {state}</b>\n"
        f"Всего в листе: {total}\n"
        f"---\n"
        f"В подготовке (NEW): {new_cnt}\n"
        f"Готовы к отправке (READY): {ready_cnt}\n"
        f"---\n"
        f"Отправлено (SENT): {sent_cnt}\n"
        f"Получен ответ (REPLIED): {replied_cnt}\n"
        f"Невалидные (INVALID): {invalid_cnt}\n"
        f"Другие статусы: {other_cnt}"
    )


def _handle_collect(chat_id: int, state: str) -> None:
    tg_send(chat_id, f"Начинаю сбор для {state}... (Google ищет)")
    try:
        # собираем
        report = upsert_leads_for_state(state)
        
        # после сбора ещё раз считаем по факту
        stats = _stats_for_state(state)

        text = (
            f"<b>Сбор завершён: {state}</b>\n"
            f"Найдено: {report['found']}\n"
            f"Создано новых: {report['created']}\n"
            f"Пропущено (дубликаты): {report['skipped']}\n\n"
            f"{stats}"
        )
        tg_send(chat_id, text, parse_mode="HTML")
    except Exception as e:
        log.error("Handle_collect error: %s", e)
        tg_send(chat_id, f"Ошибка при сборе {state}: {e}")


def _handle_send(chat_id: int, state: str, limit: int) -> None:
    tg_send(chat_id, f"Начинаю рассылку для {state} (лимит: {limit})...")
    try:
        report = run_send(state=state, limit=limit)
        text = (
            f"<b>Рассылка {state} (лимит {limit})</b>\n"
            f"---\n"
            f"✅ Отправлено: {report['sent']}\n"
            f"❌ Невалидных (-> INVALID): {report['invalid']}\n"
            f"🚫 Ошибок отправки (SMTP): {report['failed_send']}\n"
            f"🤔 Пропущено (нет Email): {report['skipped_no_email']}\n"
            f"---\n"
            f"📈 Осталось в 'READY': {report['remaining_ready']}\n"
            f"📊 В подготовке 'NEW': {report['total_new']}\n"
            f"Σ Всего в листе: {report['total_in_list']}"
        )
        tg_send(chat_id, text, parse_mode="HTML")
    except Exception as e:
        log.error("Handle_send error: %s", e)
        tg_send(chat_id, f"Ошибка при рассылке {state}: {e}")


def _imap_fetch_unseen_froms(n_last: int = 50) -> List[str]:
    host = getattr(settings, "SMTP_HOST", "mail.adm.tools")
    port = getattr(settings, "SMTP_IMAP_PORT", 993)
    username = settings.SMTP_USERNAME
    password = settings.SMTP_PASSWORD

    out: List[str] = []
    try:
        M = imaplib.IMAP4_SSL(host, port)
        M.login(username, password)
        M.select("INBOX")
        status, data = M.search(None, "UNSEEN")
        if status != "OK":
            M.logout()
            return out

        ids = data[0].split()[-n_last:]
        if not ids:
            M.logout()
            return out
            
        log.info("IMAP: found %d unseen emails", len(ids))

        for msg_id in ids:
            typ, msg_data = M.fetch(msg_id, "(RFC822)")
            if typ != "OK":
                continue
            msg = email.message_from_bytes(msg_data[0][1])
            from_hdr = email.utils.parseaddr(msg.get("From"))[1]
            if from_hdr and from_hdr != username:
                out.append(from_hdr)
                # Помечаем как прочитанное
                M.store(msg_id, "+FLAGS", "\\Seen")
        M.logout()
    except Exception as e:
        log.error("IMAP fetch failed: %s", e)
    return out


def _handle_replies(chat_id: int) -> None:
    tg_send(chat_id, "Проверяю почту (IMAP)...")
    try:
        from_list = _imap_fetch_unseen_froms()
        if not from_list:
            tg_send(chat_id, "Новых ответов нет.")
            return

        log.info("IMAP: processing replies from: %s", from_list)
        moved = 0
        for addr in from_list:
            task = clickup_client.find_task_by_email(addr)
            if task:
                log.info("IMAP: Found task %s for email %s", task['task_id'], addr)
                clickup_client.move_lead_to_status(task["task_id"], REPLIED_STATUS)
                moved += 1
                
                # --- Логика для извлечения штата ---
                list_name = task.get('list_name', '') # e.g., "LEADS-NY"
                state = list_name.replace('LEADS-', '').upper() # e.g., "NY"
                state_info = f" (Штат: {state})" if state in US_STATES else ""
                # ---
                
                tg_send(
                    chat_id,
                    f"📩 Ответ от <b>{task['clinic_name']}</b>{state_info}.\nПеренесено в «{REPLIED_STATUS}».",
                    parse_mode="HTML",
                )
            else:
                log.warning("IMAP: No task found for email %s", addr)
                
        if moved == 0:
            tg_send(chat_id, f"Получено {len(from_list)} ответов, но не нашел для них задач в ClickUp.")
    except Exception as e:
        log.error("Handle_replies error: %s", e)
        tg_send(chat_id, f"Ошибка при проверке ответов: {e}")


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
        log.warning("Ignoring message from disallowed chat_id %s", chat_id)
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
        try:
            if len(parts) == 3:
                state = parts[1].upper()
                lim_str = parts[2]
            else:
                state = USER_STATE.get(chat_id)
                lim_str = parts[1] if len(parts) > 1 else "50" # default 50
            
            if not state or state not in US_STATES:
                tg_send(chat_id, "Сначала укажи штат: /send NY 10 или выбери через /menu")
                return {"ok": True}
            
            limit = int(lim_str)
            if limit <= 0 or limit > 500:
                tg_send(chat_id, "Лимит должен быть от 1 до 500.")
                return {"ok": True}
                
            _handle_send(chat_id, state, limit)
        except (ValueError, IndexError):
            tg_send(chat_id, "Неверный формат. \nПример: /send NY 10\nИли выбери штат и напиши: /send 10")
        return {"ok": True}

    if cmd == "/stats":
        state = (parts[1].upper() if len(parts) > 1 else USER_STATE.get(chat_id))
        if not state or state not in US_STATES:
            tg_send(chat_id, "Укажи штат: /stats NY или выбери через /menu")
            return {"ok": True}
        tg_send(chat_id, _stats_for_state(state), parse_mode="HTML")
        return {"ok": True}

    if cmd == "/replies":
        _handle_replies(chat_id)
        return {"ok": True}

    tg_send(chat
