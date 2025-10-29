from fastapi import APIRouter, HTTPException
from typing import Dict, Any
from clickup_client import clickup_client, SENT_STATUS, INVALID_STATUS
from mailer import send_email
from email_validator import validate_email_if_needed

router = APIRouter()

def run_send(state: str, limit: int = 50) -> Dict[str, Any]:
    try:
        list_id = clickup_client.get_or_create_list_for_state(state)
        leads = clickup_client.get_leads_from_list(list_id)
    except Exception as e:
        raise RuntimeError(f"ClickUp error: {e}")

    sent = 0
    skipped_no_email = 0
    failed_send = 0
    invalid_count = 0

    for lead in leads:
        if sent >= limit:
            break

        email = lead.get("email")
        if not email:
            skipped_no_email += 1
            continue

        # проверка email (Verifalia и т.п.)
        is_valid = validate_email_if_needed(email)
        if is_valid is False:
            # перенос в "невалидный" (или тэг, если статуса нет)
            moved = clickup_client.move_lead_to_status(lead["task_id"], INVALID_STATUS)
            if not moved:
                clickup_client.add_tag(lead["task_id"], "invalid_email")
            invalid_count += 1
            continue

        ok = send_email(to_email=email, clinic_name=lead["clinic_name"], clinic_site=lead.get("website"))
        if ok:
            sent += 1
            try:
                clickup_client.move_lead_to_status(lead["task_id"], SENT_STATUS)
            except Exception:
                pass
        else:
            failed_send += 1

    remaining_unsent = sum(1 for l in leads if (l.get("email") and l.get("status") != SENT_STATUS))

    return {
        "state": state,
        "sent": sent,
        "skipped_no_email": skipped_no_email,
        "invalid": invalid_count,
        "failed_send": failed_send,
        "remaining_unsent": remaining_unsent,
        "total_in_list": len(leads),
    }


@router.post("/send-proposals")
def send_proposals(state: str, limit: int = 50) -> Dict[str, Any]:
    try:
        return run_send(state=state, limit=limit)
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
