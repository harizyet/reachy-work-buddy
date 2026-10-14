"""Download of the owner's calendar feed, built to be unable to reach an internal address (ADR 0035).

The feed URL is a bearer secret and arrives from the owner, so it is treated as hostile input:

* only `https` (a `webcal://` link is the same address and is read as `https://`), no user name or password in it, port 443, at most 2,048 characters;
* the host is resolved here, every address must be a public one (private, loopback, link-local, carrier-grade NAT such as Tailscale's, multicast, reserved and the IPv6
  forms that embed an IPv4 address are refused), and the connection goes to that address, not to a second lookup an attacker could answer differently;
* a redirect is followed only to another URL that passes the same checks, at most three times;
* the response is capped in size after decompression, and must look like a calendar.

Every failure is a fixed code. No message, log line or exception here contains the URL or anything the feed said.
"""

from __future__ import annotations

import asyncio
import contextvars
import ipaddress
import logging
import socket
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit

import httpx

from companion_core.calendar.ics import FeedError

MAX_URL_CHARS = 2048
MAX_BYTES = 10 * 1024 * 1024
MAX_REDIRECTS = 3
_BLOCKED_NETWORKS = tuple(ipaddress.ip_network(n) for n in (
    "100.64.0.0/10",  # carrier-grade NAT, including Tailscale
    "64:ff9b::/96", "64:ff9b:1::/48",  # NAT64 forms can carry a private IPv4 address
    "2002::/16",  # 6to4
    "2001::/32",  # Teredo
    "192.0.0.0/24", "198.18.0.0/15", "240.0.0.0/4", "::/128", "::1/128", "fc00::/7", "fe80::/10",
))

Resolver = Callable[[str, int], Awaitable[list[str]]]

# httpx logs every request URL at INFO ("HTTP Request: GET https://host/path"), and the path of a feed URL is the secret. While a feed download is running (in this task only) those
# records from httpx and httpcore are dropped; every other use of httpx in the process logs as before.
_DOWNLOADING = contextvars.ContextVar("calendar_feed_downloading", default=False)


class _NoFeedUrls(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return not _DOWNLOADING.get()


for _name in ("httpx", "httpcore"):
    logging.getLogger(_name).addFilter(_NoFeedUrls())


@dataclass
class FetchResult:
    body: bytes


async def system_resolver(host: str, port: int) -> list[str]:
    infos = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return sorted({info[4][0] for info in infos})


def is_public_address(text: str) -> bool:
    try:
        address = ipaddress.ip_address(text.split("%", 1)[0])
    except ValueError:
        return False
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        address = address.ipv4_mapped
    if any(address in network for network in _BLOCKED_NETWORKS):
        return False
    return address.is_global and not (address.is_multicast or address.is_reserved or address.is_loopback or address.is_link_local or address.is_unspecified)  # multicast counts as global to Python


def normalise_url(url: str, *, allow_local: bool = False) -> str:
    """The URL as it will be fetched, or FeedError("unsafe_url"). Does not resolve anything."""
    text = (url or "").strip()
    if not text or len(text) > MAX_URL_CHARS or any(ch in text for ch in "\r\n\t\x00 "):
        raise FeedError("unsafe_url")
    if text[:9].lower() == "webcal://":
        text = "https://" + text[9:]
    try:
        parts = urlsplit(text)
        port = parts.port
        host = parts.hostname
    except ValueError:
        raise FeedError("unsafe_url") from None
    if not allow_local:
        if parts.scheme != "https" or port not in (None, 443):
            raise FeedError("unsafe_url")
    elif parts.scheme not in ("https", "http"):
        raise FeedError("unsafe_url")
    if not host or parts.username is not None or parts.password is not None or parts.fragment:
        raise FeedError("unsafe_url")
    lowered = host.lower().rstrip(".")
    if not allow_local and (lowered == "localhost" or lowered.endswith((".localhost", ".local", ".internal", ".lan", ".home.arpa"))):
        raise FeedError("unsafe_url")
    return text


class FeedFetcher:
    def __init__(
        self, *, resolver: Resolver = system_resolver, transport: httpx.AsyncBaseTransport | None = None, allow_local: bool = False,
        timeout: float = 20.0, max_bytes: int = MAX_BYTES, max_redirects: int = MAX_REDIRECTS,
    ) -> None:
        self._resolver, self._transport, self._allow_local = resolver, transport, allow_local
        self._timeout, self._max_bytes, self._max_redirects = timeout, max_bytes, max_redirects

    async def check(self, url: str) -> str:
        """Validates the URL and its addresses without downloading anything; returns the host (not secret) for display."""
        text = normalise_url(url, allow_local=self._allow_local)
        await self._pin(text)
        return urlsplit(text).hostname or ""

    async def _pin(self, url: str) -> tuple[str, str, int]:
        parts = urlsplit(url)
        host = parts.hostname or ""
        port = parts.port or (443 if parts.scheme == "https" else 80)
        try:
            addresses = [host] if _is_literal(host) else await self._resolver(host, port)
        except (OSError, UnicodeError):
            raise FeedError("dns_failed") from None
        if not addresses:
            raise FeedError("dns_failed")
        if not self._allow_local and not all(is_public_address(a) for a in addresses):
            raise FeedError("unsafe_address")
        return host, addresses[0], port

    async def fetch(self, url: str) -> FetchResult:
        """Always a full download: the snapshot is expanded from the feed's recurrence rules over a window that moves every day, so a "not modified" copy would go stale."""
        token = _DOWNLOADING.set(True)
        try:
            async with asyncio.timeout(self._timeout * 3):
                return await self._fetch(url)
        except TimeoutError:
            raise FeedError("timeout") from None
        finally:
            _DOWNLOADING.reset(token)

    async def _fetch(self, url: str) -> FetchResult:
        current = normalise_url(url, allow_local=self._allow_local)
        # trust_env=False: a proxy named in the environment would connect on our behalf and bypass the address check.
        async with httpx.AsyncClient(transport=self._transport, timeout=self._timeout, follow_redirects=False, trust_env=False) as client:
            for _hop in range(self._max_redirects + 1):
                host, address, port = await self._pin(current)
                parts = urlsplit(current)
                literal = f"[{address}]" if ":" in address else address
                target = f"{parts.scheme}://{literal}:{port}{parts.path or '/'}" + (f"?{parts.query}" if parts.query else "")
                headers = {"Host": host if port in (80, 443) else f"{host}:{port}", "Accept": "text/calendar, text/plain;q=0.5, */*;q=0.1", "User-Agent": "reachy-calendar/1"}
                try:
                    async with client.stream("GET", target, headers=headers, extensions={"sni_hostname": host}) as response:
                        status = response.status_code
                        if status in (301, 302, 303, 307, 308):
                            location = response.headers.get("location")
                            if not location:
                                raise FeedError("redirect_refused")
                            current = normalise_url(urljoin(current, location), allow_local=self._allow_local)
                            continue
                        if status != 200:
                            raise FeedError(f"http_{status}")
                        declared = response.headers.get("content-length")
                        if declared and declared.isdigit() and int(declared) > self._max_bytes:
                            raise FeedError("too_large")
                        body = bytearray()
                        async for chunk in response.aiter_bytes():
                            body.extend(chunk)
                            if len(body) > self._max_bytes:
                                raise FeedError("too_large")
                        data = bytes(body)
                        if not data.lstrip(b"\xef\xbb\xbf \t\r\n")[:15].upper().startswith(b"BEGIN:VCALENDAR"):
                            raise FeedError("not_calendar")
                        return FetchResult(data)
                except FeedError:
                    raise
                except httpx.TimeoutException:
                    raise FeedError("timeout") from None
                except httpx.HTTPError:
                    raise FeedError("connect_failed") from None
        raise FeedError("redirect_refused")


def _is_literal(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False
