from fastapi import APIRouter
from main.schemas import SendRequest, SendResponse
from main.clickup_client import clickup_client
from main.mailer import send_email_one_lead

router = APIRouter(tags=["send"])

@router.post("/send", response_model=SendResponse)
def send_batch(req: SendRequest):
    leads = clickup_client.get_leads_ready_to_send(req.state, req.limit)

    sent_ok = 0
    failed = 0

    for lead in leads:
        ok = send_email_one_lead(
            clinic_name=lead["clinic_name"],
            website=lead.get("website", ""),
            state=req.state,
            to_email=lead["email"]
        )
        if ok:
            sent_ok += 1
            clickup_client.update_lead_status(lead["clickup_task_id"], "proposal_sent")
        else:
            failed += 1

    remaining = clickup_client.get_state_stats(req.state)["ready_to_send"]

    return SendResponse(
        ok=True,
        state=req.state,
        sent=sent_ok,
        failed=failed,
        remaining_ready_to_send=remaining
    )
