# src/ta_lab2/notifications/telegram.py
"""
Telegram notification helper for alerts and monitoring.

Environment variables:
- TELEGRAM_BOT_TOKEN: Bot token from @BotFather
- TELEGRAM_CHAT_ID: Chat ID to send messages to

If not configured, functions gracefully degrade (log warning, return False).
"""

from __future__ import annotations

import logging
import os
from typing import Optional

try:
    import requests
except ImportError:
    requests = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)


def is_configured() -> bool:
    """
    Check if Telegram is configured with bot token and chat ID.

    Returns:
        True if both TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID are set, False otherwise.
    """
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    return bool(token and chat_id)


def send_message(text: str, parse_mode: str = "HTML") -> bool:
    """
    Send a message to the configured Telegram chat.

    Args:
        text: Message text to send
        parse_mode: Telegram parse mode (HTML or Markdown), default HTML

    Returns:
        True on success, False on failure or if not configured
    """
    if not is_configured():
        logger.warning("Telegram not configured (missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID)")
        return False

    if requests is None:
        logger.error("requests library not installed - cannot send Telegram messages")
        return False

    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": parse_mode,
    }

    try:
        response = requests.post(url, json=payload, timeout=10)
        if response.status_code == 200:
            logger.debug(f"Telegram message sent successfully: {text[:50]}...")
            return True
        else:
            logger.error(f"Telegram API error: {response.status_code} - {response.text}")
            return False
    except Exception as e:
        logger.error(f"Failed to send Telegram message: {e}")
        return False


def send_alert(title: str, message: str, severity: str = "warning") -> bool:
    """
    Send a formatted alert message to Telegram.

    Args:
        title: Alert title
        message: Alert message body
        severity: Alert severity (critical, warning, info)

    Returns:
        True on success, False on failure
    """
    # Emoji prefix based on severity
    emoji_map = {
        "critical": "\U0001F534",  # Red circle
        "warning": "\U0001F7E1",   # Yellow circle
        "info": "\U0001F535",      # Blue circle
    }

    emoji = emoji_map.get(severity.lower(), "\U0001F7E1")
    formatted_text = f"{emoji} <b>{title}</b>\n\n{message}"

    return send_message(formatted_text)


def send_validation_alert(validation_result: dict) -> bool:
    """
    Send a formatted validation error alert to Telegram.

    Args:
        validation_result: Dict with keys:
            - total: total checks
            - ok: passed checks
            - gaps: gap count
            - duplicates: duplicate count
            - issues: list of issue dicts with details

    Returns:
        True on success, False on failure
    """
    gaps = validation_result.get("gaps", 0)
    duplicates = validation_result.get("duplicates", 0)
    total = validation_result.get("total", 0)
    ok = validation_result.get("ok", 0)
    issues = validation_result.get("issues", [])

    # Determine severity based on issue count
    issue_count = gaps + duplicates
    if issue_count > 10:
        severity = "critical"
    elif issue_count > 0:
        severity = "warning"
    else:
        severity = "info"

    # Build message
    message_parts = [
        f"<b>EMA Validation Failed</b>",
        f"",
        f"Summary:",
        f"  Total checks: {total}",
        f"  Passed: {ok}",
        f"  Gaps: {gaps}",
        f"  Duplicates: {duplicates}",
    ]

    # Add first 5 issues
    if issues:
        message_parts.append("")
        message_parts.append("Details (first 5):")
        for issue in issues[:5]:
            id_ = issue.get("id", "?")
            tf = issue.get("tf", "?")
            period = issue.get("period", "?")
            status = issue.get("status", "?")
            diff = issue.get("diff", 0)
            message_parts.append(f"  {id_}/{tf}/{period}: {status} (diff={diff})")

        if len(issues) > 5:
            message_parts.append(f"  ... and {len(issues) - 5} more")

    message_parts.append("")
    message_parts.append("Run validate_ema_rowcounts.py for full report")

    message = "\n".join(message_parts)
    return send_alert("EMA Validation Failed", message, severity=severity)
