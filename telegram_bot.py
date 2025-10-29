from typing import Dict, Any, Optional, List
from clickup_client import clickup_client, READY_STATUS, SENT_STATUS, REPLIED_STATUS
from telegram_notifier import send_message
from send import run_send
from email_validator import validate_email_if_needed
import imaplib, email
from email.header import decode_header
from config import settings

US_STATES = [
    "AL","AK","AZ","AR","CA","CO","CT","DE","FL","GA",
    "HI","ID","IL","IN","IA","KS","KY","LA","ME","MD",
    "MA","MI","MN","MS","MO","MT","NE","NV","NH","NJ",
    "NM","NY","NC","ND","OH","OK","OR","PA","RI","SC",
    "SD","TN","TX","UT","VT","VA","WA","WV","WI","WY"
]

# простая "память" выбора штата на время жизни процесса
USER_STATE: Dict[int, str] = {}


def _states_keyboard() -> Dict[str, Any]:
    rows = []
    row = []
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
        f"<b>Статистика {state}</b>\n"
        f"Всего в листе: {total}\n"
        f"С email: {with_email}\n"
        f"Без email: {no_email}\n"
        f"Готовы к отправке: {ready}\n"
        f"Отправлено: {sent}\n"
        f"Осталось (с email, не отправлено): {remain}"
    )


def _handle_collect(chat_id: int, state: str) -> None:
    # сейчас просто создаём лист (сбор каталога делается твоими внешними скриптами)
    list_id = clickup_client.get_or_create_list_for_state(state)
    stats = _stats_for_state(state)
    send_message(chat_id, f"Лист для штата <b>{state}</b> готов (list_id={list_id}).\n\n{stats}")


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
    send_message(chat_id, text)


def _imap_fetch_unseen_froms(n_last: int = 50) -> List[str]:
    """Простой разбор входящих (INBOX, UNSEEN) — возвращаем список адресов FROM"""
    host = "mail.adm.tools"
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
        # пометим как прочитанное
        M.store(msg_id, "+FLAGS", "\\Seen")
    M.logout()
    return out


def _handle_replies(chat_id: int) -> None:
    """Обрабатываем ответы: ищем задачу по email отправителя и переносим в статус REPLIED_STATUS"""
    from_list = _imap_fetch_unseen_froms()
    if not from_list:
        send_message(chat_id, "Новых ответов нет.")
        return

    moved = 0
    for addr in from_list:
        task = clickup_client.find_task_by_email(addr)
        if task:
            clickup_client.move_lead_to_status(task["task_id"], REPLIED_STATUS)
            moved += 1
            send_message(chat_id, f"Ответ от <b>{task['clinic_name']}</b> ({addr}). Перенесено в «{REPLIED_STATUS}».")
    if moved == 0:
        send_message(chat_id, "Ответы получены, но соответствующие задачи не найдены.")


def handle_update(update: Dict[str, Any]) -> Dict[str, Any]:
    msg = update.get("message") or update.get("edited_message")
    if not msg:
        return {"ok": True}

    chat_id = msg["chat"]["id"]
    text = (msg.get("text") or "").strip()

    # выбор штата кнопкой
    if text in US_STATES:
        USER_STATE[chat_id] = text
        send_message(chat_id, f"Штат выбран: <b>{text}</b>")
        return {"ok": True}

    parts = _parse_cmd(text)
    if not parts:
        return {"ok": True}

    cmd = parts[0].lower()

    if cmd in ("/start", "/help"):
        send_message(
            chat_id,
            "Команды:\n"
            "/menu — клавиатура штатов\n"
            "/collect NY — создать лист и показать статистику\n"
            "/send NY 10 — отправить письма (limit)\n"
            "/stats NY — сводка по штату\n"
            "/replies — обработать входящие ответы"
        )
        return {"ok": True}

    if cmd == "/menu":
        send_message(chat_id, "Выбери штат, затем используй /collect, /send, /stats", reply_markup=_states_keyboard())
        return {"ok": True}

    if cmd == "/collect":
        state = (parts[1].upper() if len(parts) > 1 else USER_STATE.get(chat_id))
        if not state or state not in US_STATES:
            send_message(chat_id, "Укажи штат: /collect NY или выбери через /menu")
            return {"ok": True}
        _handle_collect(chat_id, state)
        return {"ok": True}

    if cmd == "/send":
        # /send NY 1  или  /send 1 (если штат уже выбран)
        if len(parts) == 3:
            state = parts[1].upper()
            lim = int(parts[2])
        else:
            state = USER_STATE.get(chat_id)
            if not state:
                send_message(chat_id, "Сначала укажи штат: /send NY 1 или выбери через /menu")
                return {"ok": True}
            lim = int(parts[1]) if len(parts) > 1 else 50
        _handle_send(chat_id, state, lim)
        return {"ok": True}

    if cmd == "/stats":
        state = (parts[1].upper() if len(parts) > 1 else USER_STATE.get(chat_id))
        if not state or state not in US_STATES:
            send_message(chat_id, "Укажи штат: /stats NY или выбери через /menu")
            return {"ok": True}
        send_message(chat_id, _stats_for_state(state))
        return {"ok": True}

    if cmd == "/replies":
        _handle_replies(chat_id)
        return {"ok": True}

    # по умолчанию — подсказка
    send_message(chat_id, "Не понимаю команду. Напиши /help")
    return {"ok": True}
