"""Process-local polling health, independent of message delivery and inference."""

from dataclasses import dataclass
from datetime import UTC, datetime

import httpx

from reachy_hub.telegram_client import TelegramClient

# Above the 25-second server long poll and the 30-second HTTP timeout.
POLL_STALE_SECONDS = 60


@dataclass
class TelegramPollHealth:
    last_poll_at: datetime | None = None
    last_poll_error: str | None = None

    def snapshot(self, *, configured: bool, now: datetime | None = None) -> dict:
        age = (
            ((now or datetime.now(UTC)) - self.last_poll_at).total_seconds()
            if self.last_poll_at
            else None
        )
        return {
            "configured": configured,
            "last_poll_at": self.last_poll_at.isoformat()
            if self.last_poll_at
            else None,
            "last_poll_error": self.last_poll_error,
            "healthy": bool(
                configured
                and age is not None
                and 0 <= age < POLL_STALE_SECONDS
                and self.last_poll_error is None
            ),
        }


async def poll_updates(
    client: TelegramClient,
    health: TelegramPollHealth,
    *,
    offset: int | None = None,
    now: datetime | None = None,
) -> list[dict]:
    """One loop step, testable without real time or background-task sleeps."""
    try:
        updates = await client.get_updates(offset=offset, timeout=25)
    except httpx.HTTPStatusError as exc:
        # str(exc), response bodies, and request URLs can expose the bot token.
        health.last_poll_error = (
            f"Telegram polling returned HTTP {exc.response.status_code}"
        )
        raise
    except httpx.HTTPError:
        health.last_poll_error = "Telegram polling request failed"
        raise
    except (ValueError, KeyError, TypeError):
        health.last_poll_error = "Telegram polling response was invalid"
        raise
    health.last_poll_at = now or datetime.now(UTC)
    health.last_poll_error = None
    return updates
