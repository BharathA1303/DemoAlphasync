"""
Email Service — Async SMTP email sending for admin notifications.

Uses aiosmtplib for non-blocking email delivery. Emails are sent as
fire-and-forget background tasks to avoid blocking API responses.
All sends are logged to the email_notifications_log table.
"""

import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession
from jinja2 import Environment, FileSystemLoader, select_autoescape

from config.settings import settings
from database.connection import async_session_factory

logger = logging.getLogger(__name__)

# Jinja2 template environment
_template_env = Environment(
    loader=FileSystemLoader(
        str((Path(__file__).resolve().parent.parent / "templates" / "email").resolve())
    ),
    autoescape=select_autoescape(["html"]),
)


async def _send_smtp(to: str, subject: str, html_body: str) -> bool:
    """Send an email via SMTP. Returns True on success.

    Supports two modes depending on SMTP_USE_TLS:
      - False (default): port 587 with STARTTLS  (Gmail standard)
      - True:            port 465 with implicit SSL
    """
    if not settings.SMTP_HOST or not settings.SMTP_USER:
        logger.warning("SMTP not configured — skipping email to %s: %s", to, subject)
        return False

    try:
        import aiosmtplib

        msg = MIMEMultipart("alternative")
        msg["From"] = f"{settings.SMTP_FROM_NAME} <{settings.SMTP_FROM_EMAIL}>"
        msg["To"] = to
        msg["Subject"] = subject
        msg.attach(MIMEText(html_body, "html"))

        smtp_kwargs = dict(
            hostname=settings.SMTP_HOST,
            port=settings.SMTP_PORT,
            username=settings.SMTP_USER,
            password=settings.SMTP_PASSWORD,
            timeout=30,
        )

        if settings.SMTP_USE_TLS:
            # Port 465 — implicit SSL/TLS
            smtp_kwargs["use_tls"] = True
        else:
            # Port 587 — STARTTLS (recommended for Gmail app-passwords)
            smtp_kwargs["start_tls"] = True

        await aiosmtplib.send(msg, **smtp_kwargs)
        logger.info("Email sent to %s: %s", to, subject)
        return True
    except Exception as e:
        logger.error(
            "Failed to send email to %s [%s]: %s",
            to,
            subject,
            e,
            exc_info=True,
        )
        return False


async def _log_email(user_id, email_type: str, status: str, error: str = None):
    """Log email send attempt to the database."""
    try:
        from models.user import EmailNotificationLog

        async with async_session_factory() as db:
            log = EmailNotificationLog(
                user_id=user_id,
                email_type=email_type,
                status=status,
                error_message=error,
            )
            db.add(log)
            await db.commit()
    except Exception as e:
        logger.error(f"Failed to log email: {e}")


def _render_template(template_name: str, **context) -> str:
    """Render an email template with the given context."""
    try:
        template = _template_env.get_template(template_name)
        return template.render(**context)
    except Exception:
        # Fallback: plain text if template not found
        return f"""
        <html><body style="font-family: sans-serif; background: #0f172a; color: #e2e8f0; padding: 40px;">
        <div style="max-width: 600px; margin: 0 auto; background: #1e293b; border-radius: 12px; padding: 32px;">
            <h1 style="color: #f8fafc;">{context.get('title', 'AlphaSync Notification')}</h1>
            <p>{context.get('message', '')}</p>
            <p style="color: #94a3b8; font-size: 12px; margin-top: 24px;">— AlphaSync Team</p>
        </div></body></html>
        """


def send_email_background(
    to: str, subject: str, html_body: str, user_id=None, email_type: str = "general"
):
    """Fire-and-forget email send as a background task."""

    async def _task():
        success = await _send_smtp(to, subject, html_body)
        if user_id:
            await _log_email(
                user_id,
                email_type,
                "sent" if success else "failed",
                None if success else "SMTP send failed",
            )

    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_task())
    except RuntimeError:
        logger.warning("No running event loop — email will not be sent")


def send_registration_received_email(user):
    """Send email when a new user registers (pending approval)."""
    html = _render_template(
        "registration_received.html",
        title="Welcome to AlphaSync!",
        user_name=user.full_name or user.username,
        user_email=user.email,
        message="Your registration is complete. Our team will review and approve your account shortly.",
    )
    send_email_background(
        to=user.email,
        subject="AlphaSync — Registration Received",
        html_body=html,
        user_id=user.id,
        email_type="registration_received",
    )


def send_account_approved_email(user, duration_days: int):
    """Send email when an account is approved by admin."""
    html = _render_template(
        "account_approved.html",
        title="Your AlphaSync Account is Approved!",
        user_name=user.full_name or user.username,
        duration_days=duration_days,
        message=f"Your demo trading account has been approved for {duration_days} days. You can now log in and start trading!",
    )
    send_email_background(
        to=user.email,
        subject="AlphaSync — Account Approved",
        html_body=html,
        user_id=user.id,
        email_type="account_approved",
    )


def send_account_deactivated_email(user, reason: str = None):
    """Send email when an account is deactivated."""
    html = _render_template(
        "account_deactivated.html",
        title="AlphaSync Account Deactivated",
        user_name=user.full_name or user.username,
        reason=reason or "No reason specified",
        message="Your AlphaSync demo trading account has been deactivated.",
    )
    send_email_background(
        to=user.email,
        subject="AlphaSync — Account Deactivated",
        html_body=html,
        user_id=user.id,
        email_type="account_deactivated",
    )


def send_access_expiring_email(user, days_remaining: int):
    """Send reminder email when access is about to expire."""
    html = _render_template(
        "access_expiring.html",
        title="Your Demo Access is Expiring Soon",
        user_name=user.full_name or user.username,
        days_remaining=days_remaining,
        message=f"Your AlphaSync demo trading access will expire in {days_remaining} day(s). Contact support to extend.",
    )
    send_email_background(
        to=user.email,
        subject=f"AlphaSync — Access Expires in {days_remaining} Day(s)",
        html_body=html,
        user_id=user.id,
        email_type="access_expiring",
    )


def send_access_expired_email(user):
    """Send email when access has expired."""
    html = _render_template(
        "access_expired.html",
        title="Your Demo Access Has Expired",
        user_name=user.full_name or user.username,
        message="Your AlphaSync demo trading access has expired. Contact support to request an extension.",
    )
    send_email_background(
        to=user.email,
        subject="AlphaSync — Demo Access Expired",
        html_body=html,
        user_id=user.id,
        email_type="access_expired",
    )


async def send_phone_otp_email(to_email: str, otp: str, phone_last4: str) -> bool:
    """
    Send the phone-verification OTP via email.

    Used as a reliable fallback when FAST2SMS_API_KEY is not configured.
    The OTP is the same 6-digit code that would have gone to SMS — the user
    simply checks their inbox instead of their SMS app.
    """
    html = f"""
    <html>
    <body style="font-family:'Inter',sans-serif;background:#0f172a;color:#e2e8f0;padding:40px 20px;margin:0">
    <div style="max-width:520px;margin:0 auto;background:#1e293b;border-radius:16px;
                border:1px solid rgba(6,182,212,0.2);overflow:hidden">
        <!-- Header -->
        <div style="background:linear-gradient(135deg,#06b6d4,#0284c7);padding:28px 32px">
            <div style="font-size:1.5rem;font-weight:800;color:#fff;letter-spacing:-.02em">
                AlphaSync
            </div>
            <div style="font-size:.85rem;color:rgba(255,255,255,.75);margin-top:4px">
                Mobile Verification OTP
            </div>
        </div>
        <!-- Body -->
        <div style="padding:32px">
            <p style="margin:0 0 20px;font-size:.95rem;color:#cbd5e1;line-height:1.65">
                Your one-time password (OTP) for verifying the mobile number
                ending in <strong style="color:#06b6d4">••••{phone_last4}</strong> is:
            </p>
            <!-- OTP box -->
            <div style="text-align:center;margin:24px 0">
                <div style="display:inline-block;background:#0f172a;border:2px solid #06b6d4;
                            border-radius:14px;padding:20px 40px">
                    <span style="font-family:'Courier New',monospace;font-size:2.8rem;
                                 font-weight:900;letter-spacing:.35em;color:#06b6d4">
                        {otp}
                    </span>
                </div>
            </div>
            <p style="margin:0 0 8px;font-size:.82rem;color:#64748b;text-align:center">
                ⏱ Valid for <strong>10 minutes</strong> &nbsp;·&nbsp;
                🔒 Do not share this OTP with anyone
            </p>
            <hr style="border:none;border-top:1px solid rgba(255,255,255,.07);margin:24px 0">
            <p style="margin:0;font-size:.78rem;color:#475569;line-height:1.6">
                If you did not request this OTP, please ignore this email.
                Your account remains secure.
            </p>
        </div>
        <!-- Footer -->
        <div style="background:#0f172a;padding:16px 32px;
                    font-size:.73rem;color:#334155;text-align:center">
            © AlphaSync &nbsp;·&nbsp; This is an automated message — do not reply.
        </div>
    </div>
    </body>
    </html>
    """
    return await _send_smtp(to_email, "AlphaSync — Your Mobile Verification OTP", html)


def send_access_duration_updated_email(
    user,
    duration_days: int,
    access_expires_at,
    reactivated: bool = False,
):
    """Send email when access duration is updated or reactivated."""
    expires_at_display = (
        access_expires_at.strftime("%d %b %Y, %I:%M %p UTC")
        if access_expires_at
        else "Not set"
    )
    html = _render_template(
        "access_updated.html",
        title="Your Demo Access Has Been Updated",
        user_name=user.full_name or user.username,
        duration_days=duration_days,
        message=(
            "Your account access has been reactivated and updated by the AlphaSync team."
            if reactivated
            else "Your account demo access duration has been updated by the AlphaSync team."
        ),
        expires_at=expires_at_display,
    )
    send_email_background(
        to=user.email,
        subject="AlphaSync — Access Updated",
        html_body=html,
        user_id=user.id,
        email_type="access_updated",
    )
