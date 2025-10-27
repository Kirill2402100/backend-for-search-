import smtplib
from email.mime.text import MIMEText
from main.config import settings

EMAIL_TEMPLATE_SUBJECT = "New patient bookings for {clinic_name}"
EMAIL_TEMPLATE_BODY = """Hi {clinic_name} team,

I was reviewing {website} and noticed a few opportunities to increase high-value patient bookings (implants, whitening, cosmetic).

We build and optimize dental websites in {state} so they convert visitors into booked appointments.

Would you be open to a quick 7-minute audit this week?

Best,
Kirill

If you're not the right contact for marketing / new patient acquisition, let me know and I won't reach out again.
"""

def send_email_one_lead(clinic_name: str, website: str, state: str, to_email: str) -> bool:
    subject = EMAIL_TEMPLATE_SUBJECT.format(clinic_name=clinic_name)
    body = EMAIL_TEMPLATE_BODY.format(clinic_name=clinic_name, website=website, state=state)

    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = settings.SMTP_FROM
    msg["To"] = to_email

    try:
        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT) as server:
            server.starttls()
            server.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD)
            server.sendmail(settings.SMTP_FROM, [to_email], msg.as_string())
        return True
    except Exception:
        return False
