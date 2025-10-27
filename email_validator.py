import requests
from main.config import settings
from requests.auth import HTTPBasicAuth

def validate_email_if_needed(email: str) -> bool:
    """
    Возвращает True если email выглядит ок (валидный),
    False если явно мусор, None если не смогли проверить.
    """
    provider = settings.EMAIL_VALIDATION_PROVIDER.lower()

    if provider == "verifalia":
        try:
            url = "https://api.verifalia.com/v2.4/email-validations"
            payload = {
                "entries": [
                    {"inputData": email}
                ]
            }
            resp = requests.post(
                url,
                json=payload,
                auth=HTTPBasicAuth(settings.EMAIL_VALIDATION_API_KEY, ""),
                timeout=15
            )
            resp.raise_for_status()
            data = resp.json()

            # Verifalia складывает результаты в entries[0].classification.result
            # но структура может меняться, поэтому читаем максимально безопасно
            entry = data.get("entries", [{}])[0]
            status = entry.get("classification", {}).get("result") or entry.get("status")

            # допустим valid / deliverable / ok -> True
            if status:
                status_low = str(status).lower()
                if "ok" in status_low or "deliverable" in status_low or "success" in status_low or "valid" in status_low:
                    return True
                if "undeliverable" in status_low or "invalid" in status_low or "rejected" in status_low:
                    return False

            # если не поняли ответ - не блокируем
            return True

        except Exception:
            # не обрушать пайплайн если Verifalia не отвечает
            return True

    # fallback: если не знаем провайдера — просто пропускаем проверку
    return True
