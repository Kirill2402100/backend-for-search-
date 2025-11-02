# mailer.py
import smtplib
import logging
import re
from typing import Optional
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import formataddr, formatdate, make_msgid

from config import settings

log = logging.getLogger("mailer")

# ===== ТВОИ РЕАЛЬНЫЕ URL =====
TAPGROW_LOGO_URL = "https://pub-000b21bd62be4ca680859b2e1bedd0ce.r2.dev/email-signature/media/tapgrow-logo.png"
SVETLANA_PHOTO_URL = "https://pub-000b21bd62be4ca680859b2e1bedd0ce.r2.dev/email-signature/photo-team/miroshkina-photo.png"

ICON_MAIL = "https://pub-000b21bd62be4ca680859b2e1bedd0ce.r2.dev/email-signature/media/mail-icon.png"
ICON_GLOBE = "https://pub-000b21bd62be4ca680859b2e1bedd0ce.r2.dev/email-signature/media/website-icon.png"
ICON_PHONE = "https://pub-000b21bd62be4ca680859b2e1bedd0ce.r2.dev/email-signature/media/phone-icon.png"
ICON_LOCATION = "https://pub-000b21bd62be4ca680859b2e1bedd0ce.r2.dev/email-signature/media/location-icon.png"
ICON_BEHANCE = "https://pub-000b21bd62be4ca680859b2e1bedd0ce.r2.dev/email-signature/media/behance-icon.png"
ICON_TELEGRAM = "https://pub-000b21bd62be4ca680859b2e1bedd0ce.r2.dev/email-signature/media/telegram-icon.png"


def build_email_html(clinic_name: str, clinic_site: Optional[str], subject: str) -> str:
    # нормализуем вход
    safe_clinic = clinic_name.strip() if clinic_name else "your practice"

    safe_site_text = "your website"
    safe_site_link = "#"
    if clinic_site:
        safe_site_text = re.sub(r"^(https?://)?(www\.)?", "", clinic_site).strip("/")
        safe_site_link = clinic_site if clinic_site.startswith("http") else f"https://{clinic_site}"

    # основной текст
    body_html = f"""
<p style="margin: 0 0 16px 0;">Hi, {safe_clinic}!</p>

<p style="margin: 0 0 16px 0;">We took a quick look at <a href="{safe_site_link}" target="_blank" style="color: #1a73e8;">{safe_site_text}</a> and noticed a few areas where it could be generating more patient bookings.</p>

<p style="margin: 0 0 16px 0;">From our experience working with dental clinics, this pattern appears often:</p>

<ul style="padding-left: 20px; margin: 0 0 16px 0;">
    <li><b>Slow loading</b> → up to 40% of visitors leave before booking.</li>
    <li><b>Confusing mobile layout</b> → missed calls and form submissions.</li>
    <li><b>Weak SEO</b> → local competitors rank higher.</li>
</ul>

<p style="margin: 0 0 16px 0;">At TapGrow Studio, we specialize in building and optimizing websites for dental practices that are designed to:</p>

<ul style="padding-left: 20px; margin: 0 0 16px 0;">
    <li>✅ Attract patients through higher Google rankings</li>
    <li>✅ Build instant trust with a modern, credible design</li>
    <li>✅ Turn visitors into booked appointments with optimized UX</li>
</ul>

<p style="margin: 0 0 16px 0;">Since 2017, our 12-person team has delivered 140+ projects with 93% client retention — we know what works in the dental niche.</p>

<p style="margin: 0 0 16px 0;">
    See our work → <a href="https://behance.net/tapgrow" target="_blank" style="color: #1a73e8;">behance.net/tapgrow</a><br/>
    Read reviews → <a href="https://www.upwork.com/ag/tapgrow/" target="_blank" style="color: #1a73e8;">TapGrow on Upwork</a>
</p>

<p style="margin: 0 0 16px 0;">We’ve helped many clinics improve their results with just a few focused updates.</p>

<p style="margin: 0 0 16px 0;">If you’d like, we can prepare a free, detailed audit of your website — tailored to your clinic.</p>

<p style="margin: 0 0 16px 0;">We’ll send you a short, actionable report (speed, SEO, UX) and a 3-step improvement plan — delivered within 24 hours after your reply.</p>

<p style="margin: 0 0 16px 0;"><b>Just reply to this email — we’ll handle the rest.</b></p>
""".strip()

    # подпись
    signature_html = f"""
<table width="100%" border="0" cellspacing="0" cellpadding="0" style="margin-top:24px;">
  <tr>
    <td align="center">
      <table width="100%" border="0" cellspacing="0" cellpadding="0"
             style="width:100%; max-width:1120px; margin:0 auto;
                    background:#0b0b0b;
                    background-image:
                      radial-gradient(circle at top right, #3b5641 0%, rgba(11,11,11,0) 54%),
                      radial-gradient(circle at 12% 95%, #3b5641 0%, rgba(11,11,11,0) 45%);
                    border-radius:26px;
                    overflow:hidden;
                    font-family:Arial,Helvetica,sans-serif;">
        <tr>
          <td align="center" style="padding:40px 48px 42px 48px;">
            <!-- логотип -->
            <img src="{TAPGROW_LOGO_URL}" alt="tapgrow"
                 style="display:block; max-width:150px; height:auto; margin:0 auto 28px auto;">

            <!-- фото -->
            <img src="{SVETLANA_PHOTO_URL}" alt="Svetlana Miroshkina"
                 width="118" height="118"
                 style="display:block; border-radius:59px; border:3px solid rgba(184,255,122,0.45);
                        background:#0b0b0b; margin:0 auto 22px auto;">

            <!-- имя -->
            <p style="margin:0 0 6px 0; font-size:24px; font-weight:700; color:#ffffff; text-align:center;">
              Svetlana Miroshkina
            </p>
            <p style="margin:0 0 22px 0; font-size:14px; color:#e3e3e3; text-align:center;">
              Project Manager
            </p>

            <!-- контакты -->
            <table border="0" cellspacing="0" cellpadding="0" style="margin:0 auto; text-align:center; font-size:14px; color:#ffffff;">
              <tr>
                <td style="padding:4px 0;">
                  <img src="{ICON_MAIL}" alt="" width="20" height="20" style="vertical-align:middle; margin-right:8px;">
                  <a href="mailto:svetlana@tapgrow.studio" style="color:#b8ff7a; text-decoration:none; vertical-align:middle;">
                    svetlana@tapgrow.studio
                  </a>
                </td>
              </tr>
              <tr>
                <td style="padding:4px 0;">
                  <img src="{ICON_GLOBE}" alt="" width="20" height="20" style="vertical-align:middle; margin-right:8px;">
                  <a href="https://tapgrow.studio" style="color:#b8ff7a; text-decoration:none; vertical-align:middle;">
                    tapgrow.studio
                  </a>
                </td>
              </tr>
              <tr>
                <td style="padding:4px 0;">
                  <img src="{ICON_PHONE}" alt="" width="20" height="20" style="vertical-align:middle; margin-right:8px;">
                  <span style="vertical-align:middle; color:#ffffff;">+1 929-309-2145</span>
                </td>
              </tr>
              <tr>
                <td style="padding:4px 0;">
                  <img src="{ICON_LOCATION}" alt="" width="20" height="20" style="vertical-align:middle; margin-right:8px;">
                  <span style="vertical-align:middle; color:#ffffff;">NY, USA</span>
                </td>
              </tr>
            </table>

            <!-- соцсети (уменьшенные) -->
            <p style="margin:26px 0 0 0; text-align:center;">
              <a href="https://behance.net/tapgrow"
                 style="display:inline-block; margin-right:10px;">
                <img src="{ICON_BEHANCE}" alt="Behance" width="30" height="30" style="display:block;">
              </a>
              <a href="https://t.me/tapgrow"
                 style="display:inline-block;">
                <img src="{ICON_TELEGRAM}" alt="Telegram" width="30" height="30" style="display:block;">
              </a>
            </p>

            <!-- дисклеймер -->
            <p style="margin:34px 0 0 0; font-size:11px; line-height:1.5; color:#7b847c; text-align:center;">
              The information contained in this message is intended solely for the use by the individual or entity
              to whom it is addressed and others authorized to receive it. If you are not the intended recipient,
              please notify us immediately and delete this message.
            </p>

          </td>
        </tr>
      </table>
    </td>
  </tr>
</table>
""".strip()

    # весь html
    return f"""
<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="UTF-8">
    <title>{subject}</title>
  </head>
  <body style="margin:0; padding:0; background:#ffffff; font-family:Arial,Helvetica,sans-serif; font-size:16px; line-height:1.6; color:#111;">
    <table width="100%" border="0" cellspacing="0" cellpadding="0">
      <tr>
        <td align="center" style="padding:0;">
          <!-- текст -->
          <table width="100%" border="0" cellspacing="0" cellpadding="0" style="max-width:640px; margin:24px auto 16px auto;">
            <tr>
              <td style="text-align:left; padding:0 12px;">
                {body_html}
              </td>
            </tr>
          </table>
          <!-- подпись -->
          {signature_html}
        </td>
      </tr>
    </table>
  </body>
</html>
""".strip()


def build_email_text(clinic_name: str, clinic_site: Optional[str]) -> str:
    safe_clinic = clinic_name.strip() if clinic_name else "your practice"
    site = clinic_site or "your website"
    return (
        f"Hi, {safe_clinic}!\n\n"
        f"We took a quick look at {site} and noticed a few areas to improve.\n"
        f"Just reply to this email — we'll handle the rest."
    )


def send_email(to_email: str, clinic_name: str, clinic_site: Optional[str]) -> bool:
    subject = "Quick audit: a few easy wins for your dental website 🦷"

    html_body = build_email_html(clinic_name, clinic_site, subject)
    text_body = build_email_text(clinic_name, clinic_site)

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = formataddr(("Svetlana at TapGrow", settings.SMTP_FROM))
    msg["To"] = to_email
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain=settings.SMTP_FROM.split("@")[-1])
    msg["Reply-To"] = settings.SMTP_FROM

    msg.attach(MIMEText(text_body, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    try:
        # у тебя сейчас SSL:465 — значит так и оставляем
        if settings.SMTP_PORT == 465:
            server = smtplib.SMTP_SSL(settings.SMTP_HOST, settings.SMTP_PORT)
        else:
            server = smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT)
            server.starttls()
        server.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD)
        server.sendmail(settings.SMTP_FROM, [to_email], msg.as_string())
        server.quit()
        log.info("Email successfully sent to %s", to_email)
        return True
    except Exception as e:
        log.error("Failed to send email via SMTP: %s", e)
        return False
