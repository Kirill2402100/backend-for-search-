# mailer.py
import smtplib
import logging
from email.mime.text import MIMEText
from email.utils import formataddr
from typing import Optional
from config import settings

log = logging.getLogger("mailer")

def build_email_html(clinic_name: str, clinic_site: Optional[str]) -> str:
    safe_clinic = clinic_name.strip() if clinic_name else "your practice"
    
    # Если сайта нет, используем "your website". 
    # Если есть, но без http, добавляем его.
    safe_site_text = "your website"
    safe_site_link = "#"
    
    if clinic_site:
        safe_site_text = clinic_site.replace("https://", "").replace("http://", "")
        if not clinic_site.startswith("http"):
            safe_site_link = f"https://{clinic_site}"
        else:
            safe_site_link = clinic_site
            
    # основной текст письма
    body_html = f"""
<p>Hi, {safe_clinic}!</p>

<p>We took a quick look at <a href="{safe_site_link}" target="_blank">{safe_site_text}</a> and noticed a few areas where it could be generating more patient bookings.</p>

<p>From our experience working with dental clinics, this pattern appears often:</p>

<ul style="padding-left: 20px;">
    <li><b>Slow loading</b> → up to 40% of visitors leave before booking.</li>
    <li><b>Confusing mobile layout</b> → missed calls and form submissions.</li>
    <li><b>Weak SEO</b> → local competitors rank higher.</li>
</ul>

<p>At TapGrow Studio, we specialize in building and optimizing websites for dental practices that are designed to:</p>

<ul style="padding-left: 20px;">
    <li>✅ Attract patients through higher Google rankings</li>
    <li>✅ Build instant trust with a modern, credible design</li>
    <li>✅ Turn visitors into booked appointments with optimized UX</li>
</ul>

<p>Since 2017, our 12-person team has delivered 140+ projects with 93% client retention — we know what works in the dental niche.</p>

<p>
    See our work → <a href="https://behance.net/tapgrow" target="_blank">behance.net/tapgrow</a><br/>
    Read reviews → <a href="https://www.upwork.com/ag/tapgrow/" target="_blank">TapGrow on Upwork</a>
</p>

<p>We’ve helped many clinics improve their results with just a few focused updates.</p>

<p>If you’d like, we can prepare a free, detailed audit of your website — tailored to your clinic.</p>

<p>We’ll send you a short, actionable report (speed, SEO, UX) and a 3-step improvement plan — delivered within 24 hours after your reply.</p>

<p><b>Just reply to this email — we’ll handle the rest.</b></p>
"""

    # HTML сигнатура (скопирована точнее с твоего скриншота)
    signature_html = f"""
<div style="padding-top:20px; border-top:1px solid #e0e0e0; margin-top:20px;">
    <table cellpadding="0" cellspacing="0" border="0" style="background-color:#101010; color:#ffffff; width:100%; max-width:560px; border-radius:8px; font-family:Arial,sans-serif;">
        <tr>
            <td style="padding:24px; text-align:center;">
                <div style="font-size:18px; font-weight:bold; color:#a9f07c; margin-bottom:16px; letter-spacing:1px;">
                    tapgrow
                </div>
                
                <div>
                    <img src="https://i.ibb.co/51v1yvV/svetlana.jpg" alt="Svetlana" style="width:80px; height:80px; border-radius:50%; border:2px solid #333; margin-bottom:12px;">
                </div>
                
                <div style="font-size:18px; font-weight:600; color:#ffffff; line-height:1.2;">
                    Svetlana Miroshkina
                </div>
                <div style="font-size:14px; color:#bbbbbb; margin-bottom:20px;">
                    Project Manager
                </div>
                
                <table cellpadding="0" cellspacing="0" border="0" style="color:#ffffff; width:100%; font-size:14px; text-align:left; margin:0 auto; max-width:260px;">
                    <tr>
                        <td style="padding:4px 8px;">Email</td>
                        <td style="padding:4px 8px;">
                            <a href="mailto:svetlana@tapgrow.studio" style="color:#a9f07c; text-decoration:none;">svetlana@tapgrow.studio</a>
                        </td>
                    </tr>
                    <tr>
                        <td style="padding:4px 8px;">Studio</td>
                        <td style="padding:4px 8px;">
                            <a href="https://tapgrow.studio" style="color:#a9f07c; text-decoration:none;">tapgrow.studio</a>
                        </td>
                    </tr>
                    <tr>
                        <td style="padding:4px 8px;">Phone</td>
                        <td style="padding:4px 8px; color:#ffffff;">+1 929-309-2145</td>
                    </tr>
                    <tr>
                        <td style="padding:4px 8px;">Location</td>
                        <td style="padding:4px 8px; color:#ffffff;">NY, USA</td>
                    </tr>
                </table>
                
                <div style="padding-top:20px;">
                    <a href="https://behance.net/tapgrow" style="background:#a9f07c; color:#101010; padding:8px 14px; border-radius:6px; font-size:13px; font-weight:bold; text-decoration:none; margin:0 5px;">Behance</a>
                    <a href="https://www.upwork.com/ag/tapgrow/" style="background:#a9f07c; color:#101010; padding:8px 14px; border-radius:6px; font-size:13px; font-weight:bold; text-decoration:none; margin:0 5px;">Upwork</a>
                </div>

                <div style="font-size:10px; color:#777777; line-height:1.4; padding:20px 10px 0 10px; text-align:center;">
                    The information contained in this message is intended solely for the use by the individual or entity to whom it is addressed and others authorized to receive it. If you are not the intended recipient, please notify us immediately and delete this message.
                </div>
            </td>
        </tr>
    </table>
</div>
"""

    return f"""
<html>
  <body style="font-family: Arial, Helvetica, sans-serif; font-size:15px; line-height:1.6; color:#111; background-color:#ffffff; margin:0; padding:0;">
    <div style="max-width:600px; margin:0 auto; padding:24px;">
      <p style="font-size:17px; font-weight:600; margin-top:0; margin-bottom:24px;">
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
    msg["From"] = formataddr(("Svetlana at TapGrow", settings.SMTP_FROM))
    msg["To"] = to_email

    try:
        server = smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT)
        server.starttls() # Используем STARTTLS
        server.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD)
        server.sendmail(settings.SMTP_FROM, [to_email], msg.as_string())
        server.quit()
        log.info("Email successfully sent to %s", to_email)
        return True
    except Exception as e:
        log.error("Failed to send email via SMTP: %s", e)
        # Ты прислал smtplib.SMTP_SSL, но обычно используют .SMTP() + .starttls()
        # Если тот вариант у тебя работал, верни smtplib.SMTP_SSL(..., ...)
        return False
