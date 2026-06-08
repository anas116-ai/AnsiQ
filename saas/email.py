"""Email service — SMTP / SendGrid / SES with templating.

Email sending is **fire-and-forget** at the call site: callers should
wrap invocations in ``asyncio.create_task(...)`` so a slow SMTP server
does not block the originating HTTP request.
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass, field
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from saas.config import config

logger = logging.getLogger("ansiq.saas.email")


@dataclass
class EmailMessage:
    to: str
    subject: str
    html_body: str
    text_body: str
    cc: list[str] = field(default_factory=list)
    bcc: list[str] = field(default_factory=list)
    attachments: list[dict] = field(default_factory=list)


def schedule_email(message: EmailMessage) -> None:
    """Schedule an email send in the background.

    Falls back to a synchronous call when no running event loop is
    available (e.g., during tests).
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        # No event loop — call synchronously.
        email_service.send(message)
        return
    loop.create_task(email_service.send(message))


class EmailService:
    """Multi-provider email service."""

    def __init__(self) -> None:
        self.provider = config.email.provider
        self.from_address = config.email.from_address
        self.from_name = config.email.from_name
        # Cache the public URL once; used for verification / reset links.
        self._public_url = config.app.public_url.rstrip("/")

    def verification_url(self, token: str) -> str:
        """Return a fully-qualified verification URL."""
        return f"{self._public_url}/verify-email?token={token}"

    def reset_url(self, token: str) -> str:
        """Return a fully-qualified password-reset URL."""
        return f"{self._public_url}/reset-password?token={token}"

    async def send(self, message: EmailMessage) -> bool:
        """Send an email via the configured provider."""
        if self.provider == "sendgrid":
            return await self._send_sendgrid(message)
        elif self.provider == "ses":
            return await self._send_ses(message)
        else:
            return await self._send_smtp(message)

    async def send_verification_email(self, to: str, token: str) -> bool:
        """Send email verification link."""
        url = self.verification_url(token)
        return await self.send(
            EmailMessage(
                to=to,
                subject="Verify your AnsiQ account",
                html_body=f"""
            <h2>Welcome to AnsiQ!</h2>
            <p>Please verify your email address by clicking the link below:</p>
            <p><a href="{url}" style="background:#6366f1;color:#fff;padding:12px 24px;border-radius:8px;text-decoration:none;">Verify Email</a></p>
            <p>Or copy this link: {url}</p>
            <p>This link expires in 24 hours.</p>
            """,
                text_body=f"Verify your email: {url}",
            )
        )

    async def send_password_reset(self, to: str, token: str) -> bool:
        url = self.reset_url(token)
        return await self.send(
            EmailMessage(
                to=to,
                subject="Reset your AnsiQ password",
                html_body=f"""
            <h2>Password Reset Request</h2>
            <p>Click below to reset your password:</p>
            <p><a href="{url}" style="background:#6366f1;color:#fff;padding:12px 24px;border-radius:8px;text-decoration:none;">Reset Password</a></p>
            <p>If you didn't request this, ignore this email.</p>
            """,
                text_body=f"Reset your password: {url}",
            )
        )

    async def send_invoice(self, to: str, amount: float, pdf_url: str) -> bool:
        return await self.send(
            EmailMessage(
                to=to,
                subject=f"Your AnsiQ invoice (${amount:.2f})",
                html_body=f"""
            <h2>Invoice Available</h2>
            <p>Amount: <strong>${amount:.2f}</strong></p>
            <p><a href="{pdf_url}">View Invoice PDF</a></p>
            """,
                text_body=f"Invoice for ${amount:.2f}: {pdf_url}",
            )
        )

    # ── Provider implementations ──

    async def _send_smtp(self, message: EmailMessage) -> bool:
        try:
            import aiosmtplib

            msg = MIMEMultipart("alternative")
            msg["From"] = f"{self.from_name} <{self.from_address}>"
            msg["To"] = message.to
            msg["Subject"] = message.subject
            msg.attach(MIMEText(message.text_body, "plain"))
            msg.attach(MIMEText(message.html_body, "html"))
            await aiosmtplib.send(
                msg,
                hostname=config.email.smtp_host,
                port=config.email.smtp_port,
                username=config.email.smtp_user,
                password=config.email.smtp_password,
                start_tls=True,
            )
            logger.info("Email sent to %s via SMTP", message.to)
            return True
        except ImportError:
            logger.error(
                "aiosmtplib is not installed. Run: pip install ansiq[saas] (includes aiosmtplib)."
            )
            return False
        except Exception:
            logger.exception("SMTP send failed to %s", message.to)
            return False

    async def _send_sendgrid(self, message: EmailMessage) -> bool:
        try:
            from sendgrid import SendGridAPIClient
            from sendgrid.helpers.mail import Mail

            # SendGrid API key is stored in SMTP_PASSWORD (we keep the
            # historical config name for backward compat).
            sg = SendGridAPIClient(config.email.smtp_password)
            mail = Mail(
                from_email=self.from_address,
                to_emails=message.to,
                subject=message.subject,
                html_content=message.html_body,
                plain_text_content=message.text_body,
            )
            response = sg.send(mail)
            logger.info(
                "Email sent to %s via SendGrid (status=%s)",
                message.to,
                response.status_code,
            )
            return response.status_code in (200, 201, 202)
        except ImportError:
            logger.error("sendgrid not installed.")
            return False
        except Exception:
            logger.exception("SendGrid send failed to %s", message.to)
            return False

    async def _send_ses(self, message: EmailMessage) -> bool:
        try:
            import boto3

            region = os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION") or "us-east-1"
            client = boto3.client("ses", region_name=region)
            response = client.send_email(
                Source=f"{self.from_name} <{self.from_address}>",
                Destination={"ToAddresses": [message.to]},
                Message={
                    "Subject": {"Data": message.subject},
                    "Body": {
                        "Html": {"Data": message.html_body},
                        "Text": {"Data": message.text_body},
                    },
                },
            )
            logger.info(
                "Email sent to %s via SES (msg_id=%s)",
                message.to,
                response["MessageId"],
            )
            return True
        except ImportError:
            logger.error("boto3 not installed.")
            return False
        except Exception:
            logger.exception("SES send failed to %s", message.to)
            return False


email_service = EmailService()
