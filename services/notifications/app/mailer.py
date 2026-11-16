"""Sends email over SMTP. Development points this at Mailpit, which keeps the messages in a
local inbox instead of delivering them."""

import smtplib
from email.message import EmailMessage

from .config import Settings
from .emails import Email


class SmtpMailer:
    def __init__(self, settings: Settings):
        self.settings = settings

    def send(self, to_address: str, email: Email) -> None:
        message = EmailMessage()
        message["Subject"] = email.subject
        message["From"] = self.settings.mail_from
        message["To"] = to_address
        message.set_content(email.text)
        message.add_alternative(email.html, subtype="html")

        # Any SMTP failure propagates: the worker retries, then dead-letters the message.
        with smtplib.SMTP(self.settings.smtp_host, self.settings.smtp_port, timeout=10) as smtp:
            smtp.ehlo()
            if self.settings.smtp_starttls:
                smtp.starttls()
                smtp.ehlo()
            if self.settings.smtp_user:
                smtp.login(self.settings.smtp_user, self.settings.smtp_password)
            smtp.send_message(message)
