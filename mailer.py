# mailer.py
import smtplib
import logging
import re
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import formataddr, formatdate, make_msgid
from typing import Optional
from config import settings

log = logging.getLogger("mailer")


def build_email_html(clinic_name: str, clinic_site: Optional[str], subject: str) -> str:
    safe_clinic = clinic_name.strip() if clinic_name else "your practice"

    safe_site_text = "your website"
    safe_site_link = "#"

    if clinic_site:
        safe_site_text = re.sub(r"^(https?://)?(www\.)?", "", clinic_site).strip("/")
        if not clinic_site.startswith("http"):
            safe_site_link = f"https://{clinic_site}"
        else:
            safe_site_link = clinic_site

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
    <li style="margin-bottom: 5px;">✅ Attract patients through higher Google rankings</li>
    <li style="margin-bottom: 5px;">✅ Build instant trust with a modern, credible design</li>
    <li style="margin-bottom: 5px;">✅ Turn visitors into booked appointments with optimized UX</li>
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
"""

    avatar_url = "https://tapgrow.studio/static/svetlana.png"  # ⚠️ Поставь свою нормальную ссылку

    signature_html = f"""
<table width="100%" border="0" cellspacing="0" cellpadding="0" style="border-top:1px solid #e0e0e0; margin-top:24px; padding-top:24px;">
  <tr>
    <td>
      <table align="center" width="100%" border="0" cellspacing="0" cellpadding="0" style="max-width:560px; background-color:#101010; border-radius:8px; font-family:Arial,sans-serif;">
        <tr>
          <td align="center" style="padding:24px;">
            <p style="font-size:18px; font-weight:bold; color:#a9f07c; margin:0 0 16px 0; letter-spacing:1px;">tapgrow</p>
            <p style="margin:0 0 12px 0;">
              <img src="{avatar_url}" alt="Svetlana" width="80" height="80" style="width:80px; height:80px; border-radius:50%; border:2px solid #333;">
            </p>
            <p style="font-size:18px; font-weight:600; color:#ffffff; line-height:1.2; margin:0 0 4px 0;">Svetlana Miroshkina</p>
            <p style="font-size:14px; color:#bbbbbb; margin:0 0 20px 0;">Project Manager</p>
            <table border="0" cellspacing="0" cellpadding="0" style="color:#ffffff; font-size:14px; text-align:left; margin:0 auto; max-width:260px;">
              <tr>
                <td style="padding:4px 8px; color:#bbbbbb;">Email</td>
                <td style="padding:4px 8px;"><a href="mailto:svetlana@tapgrow.studio" style="color:#a9f07c; text-decoration:none;">svetlana@tapgrow.studio</a></td>
              </tr>
              <tr>
                <td style="padding:4px 8px; color:#bbbbbb;">Studio</td>
                <td style="padding:4px 8px;"><a href="https://tapgrow.studio" style="color:#a9f07c; text-decoration:none;">tapgrow.studio</a></td>
              </tr>
              <tr>
                <td style="padding:4px 8px; color:#bbbbbb;">Phone</td>
                <td style="padding:4px 8px; color:#ffffff;">+1 929-309-2145</td>
              </tr>
              <tr>
                <td style="padding:4px 8px; color:#bbbbbb;">Location</td>
                <td style="padding:4px 8px; color:#ffffff;">NY, USA</td>
              </tr>
            </table>
            <p style="padding-top:20px; margin: 0;">
              <a href="https://behance.net/tapgrow" style="background:#a9f07c; color:#101010; padding:8px 14px; border-radius:6px; font-size:13px; font-weight:bold; text-decoration:none; margin:0 5px;">Behance</a>
              <a href="https://www.upwork.com/ag/tapgrow/" style="background:#a9f07c; color:#101010; padding:8px 14px; border-radius:6px; font-size:13px; font-weight:bold; text-decoration:none; margin:0 5px;">Upwork</a>
            </p>
          </td>
        </tr>
      </table>
    </td>
  </tr>
  <tr>
    <td align="center" style="padding:20px 10px 0 10px;">
      <p style="font-size:10px; color:#777777; line-height:1.4; text-align:center; margin:0;">
        The information contained in this message is intended solely for the use by the individual or entity to whom it is addressed...
      </p>
    </td>
  </tr>
</table>
"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>{subject}</title>
</head>
<body style="font-family: Arial, Helvetica, sans-serif; font-size:16px; line-height:1.6; color:#111111; background-color:#ffffff; margin:0; padding:0;">
  <table width="100%" border="0" cellspacing="0" cellpadding="0">
    <tr>
      <td align="center" style="padding:24px;">
        <div style="max-width:600px; margin:0 auto;">
          {body_html}
          {signature_html}
        </div>
      </td>
    </tr>
  </table>
</body>
</html>""".strip()


def build_email_text(clinic_name: str, clinic_site: Optional[str]) -> str:
    safe_clinic = clinic_name.strip() if clinic_name else "your practice"
    site = clinic_site or "your website"
    return (
        f"Hi, {safe_clinic}!\n\n"
        f"We took a quick look at {site} and noticed a few areas to improve.\n"
        f"If you’d like, we can prepare a free, detailed audit of your website — "
        f"speed, SEO, UX — and a 3-step improvement plan.\n\n"
        f"Just reply to this email — we’ll handle the rest.\n"
        f"TapGrow Studio"
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
        # ⚠️ см. Шаг 2 про порт
        if settings.SMTP_PORT == 465:
            server = smtplib.SMTP_SSL(settings.SMTP_HOST, settings.SMTP_PORT)
        else:  # 587 по умолчанию
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
