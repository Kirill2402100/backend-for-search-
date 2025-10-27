from fastapi import APIRouter, Query
from main.schemas import StatusResponse
from main.clickup_client import clickup_client

router = APIRouter(tags=["status"])

@router.get("/status", response_model=StatusResponse)
def get_status(state: str = Query(..., example="NY")):
    stats = clickup_client.get_state_stats(state)
    return StatusResponse(
        ok=True,
        state=state,
        total=stats["total"],
        ready_to_send=stats["ready_to_send"],
        sent=stats["sent"],
        replied=stats["replied"]
    )
