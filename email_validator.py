from main.config import settings

def validate_email_deliverability(email: str) -> str:
    """
    Возвращает "valid", "invalid" или "catch_all".
    Пока что просто always valid.
    """
    if not email:
        return "invalid"
    return "valid"
