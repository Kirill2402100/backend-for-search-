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
)
from telegram_notifier import send_message as tg_send
from send import run_send
from leads import upsert_leads_for_state


# ------------------------
# Константы
# ------------------------
US_STATES = [
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA",
    "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD",
    "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ",
    "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC",
    "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY",
]

# «Память» выбранного штата на жизнь процесса
USER_STATE: Dict[int, str] = {}


# ------------------------
# Вспомогательные
# ------------------------
def _allowed_chat(chat_id: int) -> bool:
    """
    Если в переменных окружения/настройках указан TELEGRAM_CHAT_ID —
    отвечаем только этому чату. Если не указан — отвечаем всем.
    """
    want = str(getattr(settings, "TELEGRAM_CHAT_ID", "")).strip()
    return (not want) or (str(chat_id) == want)


def _states_keyboard() -> Dict[str, Any]:
    """
    Клавиатура со штатами по 5 в ряд.
    """
    rows: List[List[Dict[str, str]]] = []
    row: List[Dict[str, str]] = []
    for i, s in enumerate(US_STATES, start=1):
        row.append({"text": s})
        if i % 5 == 0:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return {
        "keyboard": rows,
        "resize_keyboard": True,
        "one_time_keyboard": False,
    }


def _parse_cmd(text: str) -> List[str]:
    parts = text.strip().split()
    return [p.strip() for p in parts if p.strip()]


def _help_text() -> str:
    return (
        "Команды:\n"
        "/menu — клавиатура штатов\n"
        "/collect NY — создать лист и СДЕЛАТЬ СБОР (синоним: /search NY)\n"
        "/send NY 10 — отправить письма (limit) или /send 10 (если штат выбран)\n"
        "/stats NY — сводка по штату\n"
        "/replies — обработать входящие ответы\n"
        "/id — показать ваш chat id"
    )


# ------------------------
# Статистика по листу
# ------------------------
def _stats_for_state(state: str) -> str:
    list_id = clickup_client.get_or_create_list_for_state(state)
    leads = clickup_client.get_leads_from_list(list_id)

    total = len(leads)
    with_email = sum(1 for l in leads if l.get("email"))
    no_email = total - with_email
    sent = sum(1 for l in leads if l.get("status") == SENT_STATUS)
    ready = sum(1 for l in leads if l.get("status") == READY_STATUS)
    remain = sum(1 for l in leads if (l.get("email") and l.get("status") != SENT_STATUS))

    return (
        f"Статистика {state}:\n"
        f"Всего в листе: {total}\n"
        f"C email: {with_email}\n"
        f"Без email: {no_email}\n"
        f"Готовы к отправке: {ready}\n"
        f"Отправлено: {sent}\n"
        f"Осталось (с email, не отправлено): {remain}"
    )


# ------------------------
# СБОР (главное)
# ------------------------
def _handle_collect(chat_id: int, state: str) -> None:
    """
    1) гарантируем лист
    2) запускаем сбор (leads.upsert_leads_for_state)
    3) шлём отчёт
    """
    report = upsert_leads_for_state(state)
    text = (
        f"Сбор завершён: <b>{report['state']}</b>\n"
        f"Найдено: {report['found']}\n"
        f"Создано новых: {report['created']}\n"
        f"Пропущено (дубликаты/ошибки): {report['skipped']}\n\n"
        f"<b>Статистика {report['state']}</b>\n"
        f"Всего в листе: {report['total_in_list']}\n"
        f"C email: {report['with_email']}\n"
        f"Без email: {report['no_email']}\n"
        f"Готовы к отправке: {report['ready']}\n"
        f"Отправлено: {report['sent']}\n"
        f"Осталось (с email, не отправлено): {report['remaining_unsent']}"
    )
    tg_send(chat_id, text, parse_mode="HTML")


# ------------------------
# ОТПРАВКА ПИСЕМ
# ------------------------
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


# ------------------------
# ОБРАБОТКА ВХОДЯЩИХ ОТВЕТОВ ПО IMAP
# ------------------------
def _imap_fetch_unseen_froms(n_last: int = 50) -> List[str]:
    """Читаем INBOX/UNSEEN и возвращаем список email-адресов отправителей."""
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
        # пометить как прочитаное
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
        tg_send(chat_id, "Ответы есть, но задач с таким email не нашли.")


# ------------------------
# ГЛАВНЫЙ ОБРАБОТЧИК АПДЕЙТА
# ------------------------
def handle_update(update: Dict[str, Any]) -> Dict[str, Any]:
    """
    Это вызывает и webhook (если включишь), и наш poller.
    """
    msg = update.get("message") or update.get("edited_message")
    if not msg:
        return {"ok": True}

    chat_id = msg.get("chat", {}).get("id")
    text = (msg.get("text") or "").strip()

    if not chat_id or not text:
        return {"ok": True}

    # ограничение по чату
    if not _allowed_chat(chat_id):
        return {"ok": True}

    # если нажали кнопку со штатом
    if text.upper() in US_STATES:
        USER_STATE[chat_id] = text.upper()
        tg_send(chat_id, f"Штат выбран: <b>{text.upper()}</b>", parse_mode="HTML")
        return {"ok": True}

    parts = _parse_cmd(text)
    if not parts:
        return {"ok": True}

    cmd = parts[0].lower()

    # /start и /help
    if cmd in ("/start", "/help"):
        tg_send(chat_id, _help_text())
        return {"ok": True}

    # /id
    if cmd == "/id":
        tg_send(chat_id, f"Ваш chat id: <code>{chat_id}</code>", parse_mode="HTML")
        return {"ok": True}

    # /menu
    if cmd == "/menu":
        tg_send(chat_id, "Выбери штат, затем используй /collect, /send, /stats", reply_markup=_states_keyboard())
        return {"ok": True}

    # /collect или /search
    if cmd in ("/collect", "/search"):
        state = (parts[1].upper() if len(parts) > 1 else USER_STATE.get(chat_id))
        if not state or state not in US_STATES:
            tg_send(chat_id, "Укажи штат: /collect NY или выбери через /menu")
            return {"ok": True}
        tg_send(chat_id, f"Начинаю сбор по {state}... (list_id={clickup_client.get_or_create_list_for_state(state)})")
        _handle_collect(chat_id, state)
        return {"ok": True}

    # /send
    if cmd == "/send":
        # /send NY 10  или  /send 10 (если штат выбран)
        if len(parts) == 3:
            state = parts[1].upper()
            limit = int(parts[2])
        else:
            state = USER_STATE.get(chat_id)
            if not state:
                tg_send(chat_id, "Сначала укажи штат: /send NY 10 или выбери через /menu")
                return {"ok": True}
            limit = int(parts[1]) if len(parts) > 1 else 50
        _handle_send(chat_id, state, limit)
        return {"ok": True}

    # /stats
    if cmd == "/stats":
        state = (parts[1].upper() if len(parts) > 1 else USER_STATE.get(chat_id))
        if not state or state not in US_STATES:
            tg_send(chat_id, "Укажи штат: /stats NY или выбери через /menu")
            return {"ok": True}
        tg_send(chat_id, _stats_for_state(state))
        return {"ok": True}

    # /replies
    if cmd == "/replies":
        _handle_replies(chat_id)
        return {"ok": True}

    # по умолчанию
    tg_send(chat_id, "Не понимаю команду. Напиши /help")
    return {"ok": True}
