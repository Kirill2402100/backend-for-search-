from fastapi import APIRouter
from main.schemas import BulkImportRequest, FBLeadRequest
from main.clickup_client import clickup_client
from main.email_validator import validate_email_deliverability

router = APIRouter(prefix="/lead", tags=["leads"])

@router.post("/bulk-import")
def bulk_import(data: BulkImportRequest):
    imported = 0
    duplicates = 0

    for item in data.leads:
        task_id = clickup_client.create_or_update_lead(
            state=data.state,
            clinic_name=item.clinic_name,
            website=item.website,
            email=None,
            source=data.source,
            extra_fields={"address": item.address, "phone": item.phone}
        )
        if task_id == "DUPLICATE":
            duplicates += 1
        else:
            imported += 1

    return {"ok": True, "imported": imported, "duplicates": duplicates}

@router.post("/from-fb")
def from_fb(data: FBLeadRequest):
    task_id = clickup_client.create_or_update_lead(
        state=data.state,
        clinic_name=data.clinic_name,
        website=data.website,
        email=data.email,
        source="facebook",
        extra_fields={}
    )

    status_msg = "Lead stored without email."
    if data.email:
        check = validate_email_deliverability(data.email)
        if check == "valid":
            clickup_client.update_lead_status(task_id, "email_valid")
            status_msg = "Lead stored. Email valid."
        else:
            clickup_client.update_lead_status(task_id, "invalid_email")
            status_msg = "Lead stored. Email invalid."

    return {"ok": True, "clickup_task_id": task_id, "message": status_msg}
