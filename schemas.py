from pydantic import BaseModel, EmailStr, HttpUrl, Field
from typing import Optional, List

class LeadImportItem(BaseModel):
    clinic_name: str = Field(..., example="Bright Smile Dental")
    website: Optional[HttpUrl] = Field(None, example="https://brightsmile-ny.com")
    address: Optional[str] = None
    phone: Optional[str] = None

class BulkImportRequest(BaseModel):
    state: str = Field(..., example="NY")
    source: str = Field(..., example="google_places")
    leads: List[LeadImportItem]

class FBLeadRequest(BaseModel):
    clinic_name: str
    website: Optional[HttpUrl] = None
    email: Optional[EmailStr] = None
    state: str

class SendRequest(BaseModel):
    state: str
    limit: int = Field(..., gt=0, le=500)

class SendResponse(BaseModel):
    ok: bool
    state: str
    sent: int
    failed: int
    remaining_ready_to_send: int

class StatusResponse(BaseModel):
    ok: bool
    state: str
    total: int
    ready_to_send: int
    sent: int
    replied: int
