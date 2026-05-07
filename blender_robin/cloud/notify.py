"""
Generic notification client. Sends render-status messages.
Supports Webhook, Slack, Feishu (Lark), and Email.

All channels default to env vars so you don't need to touch code:

    ROBIN_NOTIFY_TYPE     webhook | slack | feishu | email
    ROBIN_NOTIFY_URL      webhook URL (for webhook / slack / feishu)
    ROBIN_NOTIFY_EMAIL_*  SMTP settings (when type=email)

Usage:
    notifier = Notifier.from_env()
    notifier.send("render job 42 finished")
    # or async:
    await notifier.send_async("render job 42 finished")
"""
from __future__ import annotations

import json
import os
import smtplib
from email.mime.text import MIMEText
from typing import Optional


class NotifyError(Exception):
    pass


class Notifier:
    """Send render-status messages through the configured channel."""

    def __init__(self, channel: str = "webhook", **kwargs):
        self._channel = channel.lower()
        self._config = kwargs

    # ── Factory ───────────────────────────────────────────────────────────

    @classmethod
    def from_env(cls) -> "Notifier":
        channel = os.environ.get("ROBIN_NOTIFY_TYPE", "webhook")
        url = os.environ.get("ROBIN_NOTIFY_URL", "")
        config = {"url": url}
        if channel == "email":
            config.update(
                smtp_host=os.environ.get("ROBIN_NOTIFY_SMTP_HOST", "localhost"),
                smtp_port=int(os.environ.get("ROBIN_NOTIFY_SMTP_PORT", "25")),
                smtp_user=os.environ.get("ROBIN_NOTIFY_SMTP_USER", ""),
                smtp_pass=os.environ.get("ROBIN_NOTIFY_SMTP_PASS", ""),
                from_addr=os.environ.get("ROBIN_NOTIFY_FROM", ""),
                to_addr=os.environ.get("ROBIN_NOTIFY_TO", ""),
            )
        return cls(channel, **config)

    # ── Public API ────────────────────────────────────────────────────────

    def send(self, text: str, title: str = "") -> bool:
        """Sync send. Returns True on success."""
        try:
            return self._send(text, title)
        except Exception as e:
            raise NotifyError(f"failed to send notification via {self._channel}: {e}")

    async def send_async(self, text: str, title: str = "") -> bool:
        """Async send — uses thread pool for blocking I/O."""
        import asyncio
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, lambda: self._send(text, title))

    def _send(self, text: str, title: str = "") -> bool:
        method = getattr(self, f"_send_{self._channel}", None)
        if not method:
            raise NotifyError(f"unknown channel: {self._channel!r}")
        return method(text, title)

    # ── Channels ──────────────────────────────────────────────────────────

    def _send_webhook(self, text: str, title: str = "") -> bool:
        import urllib.request

        url = self._config.get("url", "")
        if not url:
            raise NotifyError("ROBIN_NOTIFY_URL is not set")
        payload = json.dumps({"title": title, "text": text}).encode()
        req = urllib.request.Request(
            url, data=payload, headers={"Content-Type": "application/json"}
        )
        urllib.request.urlopen(req, timeout=10)
        return True

    def _send_slack(self, text: str, title: str = "") -> bool:
        import urllib.request

        url = self._config.get("url", "")
        if not url:
            raise NotifyError("ROBIN_NOTIFY_URL is not set (expected Slack incoming webhook)")
        payload = json.dumps({
            "text": title,
            "attachments": [{"text": text}],
        }).encode()
        req = urllib.request.Request(
            url, data=payload, headers={"Content-Type": "application/json"}
        )
        urllib.request.urlopen(req, timeout=10)
        return True

    def _send_feishu(self, text: str, title: str = "") -> bool:
        import urllib.request

        url = self._config.get("url", "")
        if not url:
            raise NotifyError("ROBIN_NOTIFY_URL is not set (expected Feishu webhook)")
        payload = json.dumps({
            "msg_type": "interactive",
            "card": {
                "header": {"title": {"tag": "plain_text", "content": title}},
                "elements": [{"tag": "markdown", "content": text}],
            },
        }).encode()
        req = urllib.request.Request(
            url, data=payload, headers={"Content-Type": "application/json"}
        )
        urllib.request.urlopen(req, timeout=10)
        return True

    def _send_email(self, text: str, title: str = "") -> bool:
        smtp_host = self._config.get("smtp_host", "localhost")
        smtp_port = self._config.get("smtp_port", 25)
        smtp_user = self._config.get("smtp_user", "")
        smtp_pass = self._config.get("smtp_pass", "")
        from_addr = self._config.get("from_addr", "")
        to_addr = self._config.get("to_addr", "")

        msg = MIMEText(text, "plain", "utf-8")
        msg["Subject"] = title or "Robin Render Notification"
        msg["From"] = from_addr
        msg["To"] = to_addr

        if smtp_port == 465:
            server = smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=10)
        else:
            server = smtplib.SMTP(smtp_host, smtp_port, timeout=10)
            server.ehlo()
            server.starttls()
            server.ehlo()

        try:
            if smtp_user:
                server.login(smtp_user, smtp_pass)
            server.sendmail(from_addr, [to_addr], msg.as_string())
            return True
        finally:
            server.quit()
