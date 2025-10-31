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


def build_email_html(clinic_name: str, clinic_site: Optional[str], subject: str) -> str:
    # нормализуем имя и сайт
    safe_clinic = clinic_name.strip() if clinic_name else "your practice"

    safe_site_text = "your website"
    safe_site_link = "#"
    if clinic_site:
        safe_site_text = re.sub(r"^(https?://)?(www\.)?", "", clinic_site).strip("/")
        if not clinic_site.startswith("http"):
            safe_site_link = f"https://{clinic_site}"
        else:
            safe_site_link = clinic_site

    # твой текст письма
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

    # твой реальный URL фотки
    avatar_url = "https://pub-000b21bd62be4ca680859b2e1bedd0ce.r2.dev/email-signature/photo-team/miroshkina-photo.png"

    # подпись в стиле твоего скрина
    signature_html = f"""
<table width="100%" border="0" cellspacing="0" cellpadding="0" style="margin-top:24px;">
  <tr>
    <td align="center">
      <table width="100%" border="0" cellspacing="0" cellpadding="0" style="max-width:780px; background: radial-gradient(circle at top, #1a2a18 0%, #0b0b0b 45%, #0b0b0b 100%); border-radius:22px; overflow:hidden; font-family:Arial,Helvetica,sans-serif;">
        <tr>
          <td style="padding:40px 48px 48px 48px;" align="left">
            <p style="margin:0 0 28px 0; font-size:20px; font-weight:600; color:#b8ff7a; letter-spacing:1px;">
              tapgrow
            </p>
            <table border="0" cellspacing="0" cellpadding="0" width="100%">
              <tr valign="top">
                <td width="120" style="padding-right:28px;" align="center">
                  <img src="{avatar_url}" alt="Svetlana" width="110" height="110" style="display:block; border-radius:999px; border:3px solid rgba(184,255,122,0.35); object-fit:cover; background:#0b0b0b;">
                </td>
                <td>
                  <p style="margin:0 0 4px 0; font-size:22px; font-weight:700; color:#ffffff;">
                    Svetlana Miroshkina
                  </p>
                  <p style="margin:0 0 20px 0; font-size:14px; color:#e3e3e3;">
                    Project Manager
                  </p>
                  <table border="0" cellspacing="0" cellpadding="0" style="font-size:14px; color:#ffffff;">
                    <tr>
                      <td style="padding:3px 0; color:#a9b3a8; width:90px;">Email</td>
                      <td style="padding:3px 0;">
                        <a href="mailto:svetlana@tapgrow.studio" style="color:#b8ff7a; text-decoration:none;">svetlana@tapgrow.studio</a>
                      </td>
                    </tr>
                    <tr>
                      <td style="padding:3px 0; color:#a9b3a8;">Studio</td>
                      <td style="padding:3px 0;">
                        <a href="https://tapgrow.studio" style="color:#b8ff7a; text-decoration:none;">tapgrow.studio</a>
                      </td>
                    </tr>
                    <tr>
                      <td style="padding:3px 0; color:#a9b3a8;">Phone</td>
                      <td style="padding:3px 0; color:#ffffff;">+1 929-309-2145</td>
                    </tr>
                    <tr>
                      <td style="padding:3px 0; color:#a9b3a8;">Location</td>
                      <td style="padding:3px 0; color:#ffffff;">NY, USA</td>
                    </tr>
                  </table>
                  <p style="margin:24px 0 0 0;">
                    <a href="https://behance.net/tapgrow" style="display:inline-block; background:#b8ff7a; color:#0b0b0b; padding:8px 16px; border-radius:10px; font-size:13px; font-weight:600; text-decoration:none; margin-right:10px;">Behance</a>
                    <a href="https://www.upwork.com/ag/tapgrow/" style="display:inline-block; background:#b8ff7a; color:#0b0b0b; padding:8px 16px; border-radius:10px; font-size:13px; font-weight:600; text-decoration:none;">Upwork</a>
                  </p>
                </td>
              </tr>
            </table>
            <p style="margin:36px 0 0 0; font-size:11px; line-height:1.5; color:#7b847c;">
              The information contained in this message is intended solely for the use by the individual or entity to whom it is addressed and others authorized to receive it. If you are not the intended recipient, please notify us immediately and delete this message.
            </p>
          </td>
        </tr>
      </table>
    </td>
  </tr>
</table>
""".strip()

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
      <td align="center" style="padding:24px;">
        <div style="max-width:640px; margin:0 auto;">
          {body_html}
          {signature_html}
        </div>
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
        f"We took a quick look at {site} and noticed a few areas where it could be generating more patient bookings.\n"
        f"From our experience working with dental clinics, this pattern appears often:\n"
        f"- Slow loading\n- Confusing mobile layout\n- Weak SEO\n\n"
        f"At TapGrow Studio, we specialize in building and optimizing websites for dental practices.\n"
        f"See our work: https://behance.net/tapgrow\n"
        f"Reviews: https://www.upwork.com/ag/tapgrow/\n\n"
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

    msg.attach(MIMEText(text_body, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    try:
        server = smtplib.SMTP_SSL(settings.SMTP_HOST, settings.SMTP_PORT)
        server.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD)
        server.sendmail(settings.SMTP_FROM, [to_email], msg.as_string())
        server.quit()
        log.info("Email successfully sent to %s", to_email)
        return True
    except Exception as e:
        log.error("Failed to send email via SMTP: %s", e)
        return False
