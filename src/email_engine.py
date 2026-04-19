import os
import logging
import requests

logger = logging.getLogger(__name__)

class EmailEngine:
    def __init__(self):
        self.api_key = os.getenv("RESEND_API_KEY")
        self.from_email = os.getenv("FROM_EMAIL", "Business Spy <intelligence@bizspy.ai>")
        self.enabled = bool(self.api_key)

        if not self.enabled:
            logger.warning("EmailEngine: RESEND_API_KEY not found. Notifications disabled.")

    def send_report_ready(self, to_email, niche_name, report_url):
        if not self.enabled:
            logger.info(f"EmailEngine [DEBUG]: Skipping email to {to_email}. Report: {report_url}")
            return False

        try:
            url = "https://api.resend.com/emails"
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }
            payload = {
                "from": self.from_email,
                "to": to_email,
                "subject": f"Forensic Intelligence Delivered: {niche_name}",
                "html": f"""
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
            }
            
            response = requests.post(url, json=payload, headers=headers, timeout=10)
            response.raise_for_status()
            logger.info(f"EmailEngine: Report notification sent to {to_email}")
            return True
            
        except Exception as e:
            logger.error(f"EmailEngine: Failed to send email to {to_email}: {e}")
            return False
