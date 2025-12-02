# send.py
import re
import time
import logging
from typing import Dict, Any, Optional

from fastapi import APIRouter, HTTPException

from clickup_client import (
    clickup_client,
    READY_STATUS,
    SENT_STATUS,
    INVALID_STATUS,
    NEW_STATUS,
)
from mailer import send_email
from email_validator import validate_email_if_needed
from utils import _task_status_str

log = logging.getLogger("sender")
router = APIRouter()


def _parse_details(description: str) -> Dict[str, str]:
    """
    Парсит Email и Website из поля 'description' задачи.
    Поддерживает переносы строк и лишние пробелы.
    """
    email = None
    website = None

    if not description:
        return {}

    email_match = re.search(
        r"^\s*Email:?\s*[\r\n\s]*([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})",
        description,
        re.IGNORECASE | re.MULTILINE,
    )
    if email_match:
        email = email_match.group(1).strip()

    website_match = re.search(
        r"^\s*Website:?\s*[\r\n\s]*([^\s]+)",  # любой непробельный блок
        description,
        re.IGNORECASE | re.MULTILINE,
    )
    if website_match:
        raw = website_match.group(1).strip()
        # убираем хвостовую пунктуацию вида ),.;,
        raw = re.sub(r"[)\].,;]+$", "", raw)
        website = raw

    return {"email": email, "website": website}


def run_send(state: str, limit: int = 50) -> Dict[str, Any]:
    try:
        list_id = clickup_client.get_or_create_list_for_state(state)
        all_tasks = clickup_client.get_leads_from_list(list_id)
    except Exception as e:
        log.error("run_send: ClickUp error on get_leads_from_list: %s", e)
        raise RuntimeError(f"ClickUp error: {e}")

    # готовые к отправке
    ready_tasks = [t for t in all_tasks if _task_status_str(t).upper() == READY_STATUS]

    tasks_to_process = ready_tasks[: max(0, int(limit))]
    log.info(
        "run_send for %s: Total=%d, Ready=%d, Processing=%d",
        state,
        len(all_tasks),
        len(ready_tasks),
        len(tasks_to_process),
    )

    sent = 0
    skipped_no_email = 0
    failed_send = 0
    invalid_count = 0

    for lead_stub in tasks_to_process:
        task_id = lead_stub.get("id")
        clinic_name = lead_stub.get("name")
        if not task_id or not clinic_name:
            continue

        try:
            task_details = clickup_client.get_task_details(task_id)
            description = task_details.get("description", "")

            parsed = _parse_details(description)
            email = parsed.get("email")
            website = parsed.get("website")

            if not email:
                log.warning(
                    "Task %s (%s) is READY but has no 'Email:' in description.",
                    task_id,
                    clinic_name,
                )
                skipped_no_email += 1
                continue

            # Валидация e-mail (если включена)
            log.info("Validating email %s for %s", email, clinic_name)
            is_valid = validate_email_if_needed(email)
            if is_valid is False:
                log.warning("Email %s for %s is INVALID.", email, clinic_name)
                clickup_client.move_lead_to_status(task_id, INVALID_STATUS)
                invalid_count += 1
                continue

            # Теги/кастом для аналитики Brevo
            brevo_tags = ["proposals", state.lower()]
            brevo_custom = {
                "task_id": task_id,
                "clinic_name": clinic_name,
                "state": state,
                "list_id": list_id,
                "website": website or "",
            }

            log.info(
                "Sending email to %s for %s (tags=%s custom=%s)",
                email,
                clinic_name,
                brevo_tags,
                brevo_custom,
            )

            ok = send_email(
                to_email=email,
                clinic_name=clinic_name,
                clinic_site=website,  # может быть None — mailer обрабатывает
                tags=brevo_tags,
                custom=brevo_custom,
            )

            if ok:
                sent += 1
                clickup_client.move_lead_to_status(task_id, SENT_STATUS)
                # Небольшая пауза, чтобы не ловить троттлинг у SMTP-провайдера
                time.sleep(0.4)
            else:
                failed_send += 1

        except Exception as e:
            log.error("run_send: Failed to process task %s: %s", task_id, e)
            failed_send += 1

    processed_count = sent + invalid_count + failed_send + skipped_no_email
    remaining_ready = max(0, len(ready_tasks) - processed_count)
    new_count = sum(1 for t in all_tasks if _task_status_str(t).upper() == NEW_STATUS)

    return {
        "state": state,
        "sent": sent,
        "skipped_no_email": skipped_no_email,
        "invalid": invalid_count,
        "failed_send": failed_send,
        "remaining_ready": remaining_ready,
        "total_new": new_count,
        "total_in_list": len(all_tasks),
    }


@router.post("/send-proposals")
def send_proposals(state: str, limit: int = 50) -> Dict[str, Any]:
    try:
        return run_send(state=state, limit=limit)
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
