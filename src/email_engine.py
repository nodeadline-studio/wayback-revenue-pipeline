import os
import logging
import smtplib
import requests
from email.utils import formataddr, parseaddr
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

logger = logging.getLogger(__name__)

class EmailEngine:
    def __init__(self):
        self.api_key = os.getenv("RESEND_API_KEY")
        self.from_email = os.getenv("FROM_EMAIL", "SlopRadar <noreply@mail.leadideal.com>")
        self.smtp_host = os.getenv("SMTP_HOST") or os.getenv("SMTP_SERVER", "smtp.gmail.com")
        self.smtp_port = int(os.getenv("SMTP_PORT", "587"))
        self.smtp_user = os.getenv("SMTP_USER") or os.getenv("SMTP_USERNAME") or os.getenv("GMAIL_EMAIL")
        self.smtp_password = os.getenv("SMTP_PASSWORD") or os.getenv("GMAIL_APP_PASSWORD")
        self.smtp_from_email = os.getenv("SMTP_FROM_EMAIL") or self.smtp_user or os.getenv("EMAIL_FROM")
        self.smtp_enabled = bool(self.smtp_user and self.smtp_password)
        self.resend_enabled = bool(self.api_key)
        self.enabled = self.smtp_enabled or self.resend_enabled

        if self.smtp_enabled:
            logger.info("EmailEngine: SMTP delivery enabled; using SMTP as primary sender.")
        elif self.resend_enabled:
            logger.info("EmailEngine: SMTP not configured; using Resend.")
        else:
            logger.warning("EmailEngine: No SMTP or Resend credentials found. Notifications disabled.")

    def _send_via_smtp(self, to_email, subject, html):
        msg = MIMEMultipart("alternative")
        from_name, parsed_from = parseaddr(self.from_email)
        smtp_from = self.smtp_from_email or parsed_from or self.smtp_user
        msg["From"] = formataddr((from_name or "SlopRadar", smtp_from))
        msg["To"] = ", ".join(to_email) if isinstance(to_email, list) else to_email
        msg["Subject"] = subject
        msg.attach(MIMEText(html, "html"))

        with smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=15) as server:
            server.starttls()
            server.login(self.smtp_user, self.smtp_password)
            server.send_message(msg)

    def _send_via_resend(self, to_email, subject, html):
        url = "https://api.resend.com/emails"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "from": self.from_email,
            "to": to_email,
            "subject": subject,
            "html": html,
        }

        response = requests.post(url, json=payload, headers=headers, timeout=10)
        response.raise_for_status()

    def _deliver(self, to_email, subject, html, log_label):
        if not self.enabled:
            logger.info(f"EmailEngine [DEBUG]: Skipping {log_label}. Recipient={to_email}")
            return False

        if self.smtp_enabled:
            try:
                self._send_via_smtp(to_email, subject, html)
                logger.info(f"EmailEngine: {log_label} sent via SMTP to {to_email}")
                return True
            except Exception as e:
                logger.error(f"EmailEngine: SMTP failed for {log_label} to {to_email}: {e}")

        if self.resend_enabled:
            try:
                self._send_via_resend(to_email, subject, html)
                logger.info(f"EmailEngine: {log_label} sent via Resend to {to_email}")
                return True
            except Exception as e:
                logger.error(f"EmailEngine: Resend failed for {log_label} to {to_email}: {e}")

        return False

    def send_report_ready(self, to_email, niche_name, report_url):
        subject = f"Forensic Intelligence Delivered: {niche_name}"
        html = f"""
                    <div style="font-family: sans-serif; max-width: 600px; margin: 0 auto; padding: 20px; color: #0f172a;">
                        <h1 style="color: #7c5cfc; font-size: 24px;">Investigation Complete.</h1>
                        <p style="font-size: 16px; line-height: 1.6;">
                            Our forensic analysts have finished mining the competitive history for <strong>{niche_name}</strong>.
                            Your strategic roadmap is now ready for review.
                        </p>
                        <div style="margin: 30px 0;">
                            <a href="{report_url}" style="background-color: #7c5cfc; color: white; padding: 12px 24px; text-decoration: none; border-radius: 8px; font-weight: bold; display: inline-block;">
                                Access Intelligence Report
                            </a>
                        </div>
                        <p style="font-size: 14px; color: #64748b;">
                            You can also access all your historical scans via your <a href="https://bizspy.netlify.app/dashboard.html">Founder Dashboard</a>.
                        </p>
                        <hr style="border: 0; border-top: 1px solid #e2e8f0; margin: 32px 0;">
                        <footer style="font-size: 12px; color: #94a3b8;">
                            © 2026 Business Spy Forensic Studio. All rights reserved.
                        </footer>
                    </div>
                """
        return self._deliver(to_email, subject, html, "report notification")

    def send_admin_lead(self, lead_email, target_url, report_url, mode="signal"):
        admin_to = os.getenv("ADMIN_EMAIL", "")
        if not admin_to:
            logger.info("EmailEngine: ADMIN_EMAIL not set, skipping admin notification.")
            return False
        recipients = [e.strip() for e in admin_to.split(",") if e.strip()]
        subject = f"[SlopRadar Lead] {lead_email or 'anon'} scanned {target_url}"
        html = f"""
                    <div style="font-family: sans-serif; max-width: 600px; padding: 20px; color: #0f172a;">
                        <h2 style="color: #7c5cfc;">New SlopRadar lead ({mode})</h2>
                        <p><strong>Email:</strong> {lead_email or '(not provided)'}</p>
                        <p><strong>Target:</strong> <a href="{target_url}">{target_url}</a></p>
                        <p><strong>Report:</strong> <a href="{report_url}">{report_url}</a></p>
                        <hr style="border:0;border-top:1px solid #e2e8f0;margin:24px 0;">
                        <p style="font-size:12px;color:#94a3b8;">Auto-notification from SlopRadar API.</p>
                    </div>
                """
        return self._deliver(recipients, subject, html, "admin lead notification")
