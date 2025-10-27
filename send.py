from fastapi import APIRouter, HTTPException
from typing import List, Dict, Any
from clickup_client import clickup_client
from mailer import send_email
from telegram_notifier import send_telegram_message

router = APIRouter()


@router.post("/send-proposals")
def send_proposals(state: str, limit: int = 50) -> Dict[str, Any]:
    try:
        list_id = clickup_client.get_or_create_list_for_state(state)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"ClickUp list error: {e}")

    try:
        leads = clickup_client.get_leads_from_list(list_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Can't load leads: {e}")

    sent = 0
    skipped_no_email = 0
    failed_send = 0
    processed_tasks: List[str] = []

    for lead in leads:
        if sent >= limit:
            break

        email = lead.get("email")
        clinic_name = lead.get("clinic_name") or "your practice"
        website = lead.get("website")

        if not email:
            skipped_no_email += 1
            continue

        ok = send_email(to_email=email, clinic_name=clinic_name, clinic_site=website)

        if ok:
            sent += 1
            processed_tasks.append(lead["task_id"])
            try:
                clickup_client.move_lead_to_status(task_id=lead["task_id"], new_status="кп отправлено")
            except Exception:
                pass
        else:
            failed_send += 1

    report = (
        f"<b>Рассылка по штату {state}</b>\n"
        f"Отправлено писем: {sent}\n"
        f"Без email: {skipped_no_email}\n"
        f"Ошибок отправки: {failed_send}\n"
        f"Обновлённых карточек: {len(processed_tasks)}"
    )
    send_telegram_message(report)

    return {
        "state": state,
        "sent": sent,
        "skipped_no_email": skipped_no_email,
        "failed_send": failed_send,
        "updated_tasks": processed_tasks,
    }
