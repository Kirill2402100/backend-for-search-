# send.py
import re
import logging
from fastapi import APIRouter, HTTPException
from typing import Dict, Any, List, Optional

from clickup_client import (
    clickup_client,
    READY_STATUS,
    SENT_STATUS,
    INVALID_STATUS
)
from mailer import send_email
from email_validator import validate_email_if_needed
from utils import _task_status_str # <-- 🟢 ИСПРАВЛЕН ИМПОРТ

log = logging.getLogger("sender")
router = APIRouter()

def _parse_details(description: str) -> Dict[str, str]:
    """
    Парсит Email и Website из 'description' (заметок) задачи.
    Ожидает формат:
    Email: test@example.com
    Website: https://example.com
    """
    email = None
    website = None

    if not description:
        return {}

    # re.IGNORECASE - неважно, 'Email:' или 'email:'
    # re.MULTILINE - ищет в каждой строке
    email_match = re.search(
        r"^\s*Email:\s*([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})",
        description,
        re.IGNORECASE | re.MULTILINE
    )
    if email_match:
        email = email_match.group(1).strip()

    website_match = re.search(
        r"^\s*Website:\s*(https?://[^\s]+)",
        description,
        re.IGNORECASE | re.MULTILINE
    )
    if website_match:
        website = website_match.group(1).strip()
    
    return {"email": email, "website": website}


def run_send(state: str, limit: int = 50) -> Dict[str, Any]:
    try:
        list_id = clickup_client.get_or_create_list_for_state(state)
        # 1. Получаем ВСЕ задачи (легкие)
        all_tasks = clickup_client.get_leads_from_list(list_id)
    except Exception as e:
        log.error("run_send: ClickUp error on get_leads_from_list: %s", e)
        raise RuntimeError(f"ClickUp error: {e}")

    # 2. Фильтруем по статусу "READY"
    ready_tasks = []
    for t in all_tasks:
        # Используем импортированную функцию
        if _task_status_str(t).upper() == READY_STATUS: 
            ready_tasks.append(t)
    
    # 3. Берем 'limit' из готовых к отправке
    tasks_to_process = ready_tasks[:limit]
    
    log.info(
        "run_send for %s: Total=%d, Ready=%d, Processing=%d",
        state, len(all_tasks), len(ready_tasks), len(tasks_to_process)
    )

    sent = 0
    skipped_no_email = 0
    failed_send = 0
    invalid_count = 0

    # 4. Обрабатываем только выбранные
    for lead_stub in tasks_to_process:
        task_id = lead_stub.get("id")
        clinic_name = lead_stub.get("name")
        if not task_id or not clinic_name:
            continue
            
        try:
            # 5. Получаем ПОЛНЫЕ детали (с 'description')
            task_details = clickup_client.get_task_details(task_id)
            description = task_details.get("description", "")
            
            # 6. Парсим 'description'
            parsed_data = _parse_details(description)
            email = parsed_data.get("email")
            website = parsed_data.get("website")

            if not email:
                log.warning("Task %s (%s) is READY but has no 'Email:' in description.", task_id, clinic_name)
                skipped_no_email += 1
                continue

            # 7. Валидация
            log.info("Validating email %s for %s", email, clinic_name)
            is_valid = validate_email_if_needed(email)
            
            if is_valid is False:
                log.warning("Email %s for %s is INVALID.", email, clinic_name)
                # Переносим в INVALID
                clickup_client.move_lead_to_status(task_id, INVALID_STATUS)
                invalid_count += 1
                continue
            
            # 8. Отправка
            log.info("Sending email to %s for %s", email, clinic_name)
            ok = send_email(
                to_email=email,
                clinic_name=clinic_name,
                clinic_site=website # website может быть None, mailer.py это обработает
            )
            
            if ok:
                log.info("Email sent to %s", email)
                sent += 1
                # Переносим в SENT
                clickup_client.move_lead_to_status(task_id, SENT_STATUS)
            else:
                log.warning("Failed to send email to %s", email)
                failed_send += 1

        except Exception as e:
            log.error("run_send: Failed to process task %s: %s", task_id, e)
            failed_send += 1

    # 7. Считаем статистику для отчета
    
    # Пересчитываем, сколько ОСТАЛОСЬ в "READY" (total_ready - (sent + invalid + failed))
    remaining_ready = len(ready_tasks) - (sent + invalid_count + failed_send)
    
    # Считаем, сколько в "NEW"
    new_count = sum(1 for t in all_tasks if _task_status_str(t).upper() == NEW_STATUS)

    return {
        "state": state,
        "sent": sent,
        "skipped_no_email": skipped_no_email, # Готовы, но нет Email в заметках
        "invalid": invalid_count,
        "failed_send": failed_send,
        "remaining_ready": remaining_ready, # Осталось в "READY"
        "total_new": new_count,             # Всего в "NEW" (в подготовке)
        "total_in_list": len(all_tasks),
    }


@router.post("/send-proposals")
def send_proposals(state: str, limit: int = 50) -> Dict[str, Any]:
    try:
        return run_send(state=state, limit=limit)
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
