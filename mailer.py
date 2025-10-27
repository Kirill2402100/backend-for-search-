import smtplib
from email.mime.text import MIMEText
from email.utils import formataddr
from typing import Optional
from config import settings


def build_email_html(clinic_name: str, clinic_site: Optional[str]) -> str:
    safe_clinic = clinic_name.strip() if clinic_name else "your practice"
    safe_site = clinic_site.strip() if clinic_site else "your website"

    # основной текст письма
    body_html = f"""
<p>Hi, {safe_clinic}!</p>

<p>We took a quick look at {safe_site} and noticed a few areas where it could be generating more patient bookings.</p>

<p>From our experience working with dental clinics, this pattern appears often:</p>

<ul>
  <li><b>Slow loading</b> → up to 40% of visitors leave before booking.</li>
  <li><b>Confusing mobile layout</b> → missed calls and form submissions.</li>
  <li><b>Weak SEO</b> → local competitors rank higher.</li>
</ul>

<p>At TapGrow Studio, we specialize in building and optimizing websites for dental practices that are designed to:</p>

<ul>
  <li>✅ Attract patients through higher Google rankings</li>
  <li>✅ Build instant trust with a modern, credible design</li>
  <li>✅ Turn visitors into booked appointments with optimized UX</li>
</ul>

<p>Since 2017, our 12-person team has delivered 140+ projects with 93% client retention — we know what works in the dental niche.</p>

<p>
  See our work → <a href="https://behance.net/tapgrow" target="_blank">behance.net/tapgrow</a><br/>
  Read reviews → TapGrow on Upwork
</p>

<p>We’ve helped many clinics improve their results with just a few focused updates.</p>

<p>If you’d like, we can prepare a free, detailed audit of your website — tailored to your clinic.</p>

<p>We’ll send you a short, actionable report (speed, SEO, UX) and a 3-step improvement plan — delivered within 24 hours after your reply.</p>

<p><b>Just reply to this email — we’ll handle the rest.</b></p>
"""

    # HTML сигнатура из твоего письма.
    # Я делаю упрощённый, "без зелёного фона-градиента", но со всем содержимым:
    # имя Светланы, роль, телефон, email, город, бренд TapGrow.
    # Если хочешь 1-в-1 блок с тёмной карточкой как на скрине — можно вставить полную верстку с <table>, это просто будет длиннее.
    signature_html = """
<hr style="margin:32px 0;border:none;border-top:1px solid #444;" />

<div style="font-family:Arial,Helvetica,sans-serif; max-width:480px; background:#1a1a1a; border-radius:12px; padding:24px; color:#f2f2f2;">
  <div style="text-align:center; font-size:14px; line-height:1.4; color:#9fe870; font-weight:600; margin-bottom:16px;">
    tapgrow
  </div>

  <div style="text-align:center; margin-bottom:16px;">
    <img src="https://i.ibb.co/k3vQ5rY/avatar-placeholder.png" alt="Svetlana" style="width:72px;height:72px;border-radius:50%;object-fit:cover;border:2px solid #333;" />
  </div>

  <div style="text-align:center; font-size:16px; font-weight:600; color:#fff;">
    Svetlana Miroshkina
  </div>
  <div style="text-align:center; font-size:13px; color:#bdbdbd; margin-bottom:20px;">
    Project Manager
  </div>

  <div style="font-size:14px; color:#f2f2f2; line-height:1.6; text-align:center;">
    <div style="margin-bottom:4px;">
      <span style="color:#9fe870;">✉</span>
      <a href="mailto:svetlana@tapgrow.studio" style="color:#9fe870; text-decoration:none;">&nbsp;Email</a>
    </div>
    <div style="margin-bottom:4px;">
      <span style="color:#9fe870;">🌐</span>
      <span style="color:#f2f2f2;">&nbsp;tapgrow.studio</span>
    </div>
    <div style="margin-bottom:4px;">
      <span style="color:#9fe870;">📞</span>
      <span style="color:#f2f2f2;">&nbsp;+1 929-309-2145</span>
    </div>
    <div style="margin-bottom:12px;">
      <span style="color:#9fe870;">📍</span>
      <span style="color:#f2f2f2;">&nbsp;NY, USA</span>
    </div>

    <div style="text-align:center;">
      <a href="https://behance.net/tapgrow" style="display:inline-block;background:#9fe870;color:#000;font-size:12px;font-weight:600;padding:6px 10px;border-radius:6px;text-decoration:none;">
        Behance
      </a>
    </div>
  </div>

  <div style="font-size:10px; line-height:1.4; color:#777; text-align:center; margin-top:24px;">
    The information contained in this message is intended solely for the use by the individual or entity
    to whom it is addressed and others authorized to receive it. If you are not the intended recipient,
    please notify us immediately and delete this message.
  </div>
</div>
"""

    return f"""
<html>
  <body style="font-family: Arial, Helvetica, sans-serif; font-size:15px; line-height:1.5; color:#111; background-color:#ffffff;">
    <div style="max-width:600px; margin:0 auto; padding:24px;">
      <p style="font-size:16px; font-weight:600; margin-top:0; margin-bottom:24px;">
        Quick audit: a few easy wins for your dental website 🦷
      </p>
      {body_html}
      {signature_html}
    </div>
  </body>
</html>
""".strip()


def send_email(to_email: str, clinic_name: str, clinic_site: Optional[str]) -> bool:
    subject = "Quick audit: a few easy wins for your dental website 🦷"
    html_body = build_email_html(clinic_name, clinic_site)

    msg = MIMEText(html_body, "html", "utf-8")
    msg["Subject"] = subject
    msg["From"] = formataddr(("TapGrow Studio", settings.SMTP_FROM))
    msg["To"] = to_email

    try:
        server = smtplib.SMTP_SSL(settings.SMTP_HOST, settings.SMTP_PORT)
        server.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD)
        server.sendmail(settings.SMTP_FROM, [to_email], msg.as_string())
        server.quit()
        return True
    except Exception:
        return False
