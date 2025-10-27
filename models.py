from enum import Enum

class LeadStatus(str, Enum):
    NEW = "new"
    EMAIL_VALID = "email_valid"
    INVALID_EMAIL = "invalid_email"
    PROPOSAL_SENT = "proposal_sent"
    REPLIED = "replied"
