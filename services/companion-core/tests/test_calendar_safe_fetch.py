"""ADR 0035: the feed URL is hostile input. Nothing here opens a socket: the resolver is injected and the transport is httpx's mock, so each test names the address it pretends
the host resolves to. A failure is a fixed code that never contains the URL."""

import asyncio

import httpx
import pytest
from companion_core.calendar.ics import FeedError
from companion_core.calendar.safe_fetch import (
    FeedFetcher,
    is_public_address,
    normalise_url,
)

SECRET_URL = "https://calendar.example.com/private/abcdef-secret-token/basic.ics"
CALENDAR = b"BEGIN:VCALENDAR\r\nVERSION:2.0\r\nEND:VCALENDAR\r\n"


def resolver(*addresses):
    async def resolve(host, port):
        return list(addresses)
    return resolve


def fetcher(handler, *addresses, **kw):
    return FeedFetcher(resolver=resolver(*(addresses or ("93.184.216.34",))), transport=httpx.MockTransport(handler), **kw)


def fetch(f, url=SECRET_URL):
    return asyncio.run(f.fetch(url))


def code(f, url=SECRET_URL):
    with pytest.raises(FeedError) as caught:
        fetch(f, url)
    assert "secret-token" not in str(caught.value) and "calendar.example.com" not in str(caught.value)
    return caught.value.code


def ok(request):
    return httpx.Response(200, content=CALENDAR, headers={"content-type": "text/calendar"})


# --- the URL ---------------------------------------------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("url", [
    "http://calendar.example.com/a.ics", "ftp://calendar.example.com/a.ics", "file:///etc/passwd", "gopher://calendar.example.com/", "javascript:alert(1)",
    "https://user:pass@calendar.example.com/a.ics", "https://calendar.example.com:8443/a.ics", "https://calendar.example.com/a.ics#frag", "https:///a.ics", "", "   ",
    "https://localhost/a.ics", "https://calendar.localhost/a.ics", "https://printer.local/a.ics", "https://db.internal/a.ics", "https://calendar.example.com/a b.ics",
    "https://calendar.example.com/" + "a" * 2100,
])
def test_unsafe_urls_are_rejected_before_any_lookup(url):
    with pytest.raises(FeedError) as caught:
        normalise_url(url)
    assert caught.value.code == "unsafe_url"


def test_webcal_is_read_as_https():
    assert normalise_url("webcal://calendar.example.com/a.ics") == "https://calendar.example.com/a.ics"
    assert normalise_url("WEBCAL://calendar.example.com/a.ics").startswith("https://")


@pytest.mark.parametrize("address", [
    "127.0.0.1", "127.1.2.3", "10.0.0.5", "172.16.0.1", "172.31.255.255", "192.168.1.1", "169.254.169.254", "100.64.0.1", "100.100.100.100", "0.0.0.0", "224.0.0.1",
    "255.255.255.255", "198.18.0.1", "192.0.0.1", "::1", "::", "fe80::1", "fc00::1", "fd12:3456::1", "::ffff:10.0.0.1", "::ffff:127.0.0.1", "64:ff9b::a00:1", "2002:c0a8:101::1",
    "2001:0:4136:e378:8000:63bf:3fff:fdd2", "not-an-ip",
])
def test_internal_addresses_are_not_public(address):
    assert not is_public_address(address)


@pytest.mark.parametrize("address", ["93.184.216.34", "8.8.8.8", "1.1.1.1", "2606:4700:4700::1111"])
def test_public_addresses_are_public(address):
    assert is_public_address(address)


@pytest.mark.parametrize("address", ["127.0.0.1", "10.1.2.3", "192.168.0.10", "169.254.169.254", "100.64.5.5", "::1", "fd00::1"])
def test_a_host_that_resolves_to_an_internal_address_is_refused(address):
    called = []
    f = fetcher(lambda request: called.append(request) or ok(request), address)
    assert code(f) == "unsafe_address" and not called  # no request was made


def test_one_internal_address_among_public_ones_is_enough_to_refuse():
    f = fetcher(ok, "93.184.216.34", "10.0.0.5")  # a name that answers with both is how a rebinding attack hides
    assert code(f) == "unsafe_address"


@pytest.mark.parametrize("url", ["https://127.0.0.1/a.ics", "https://10.0.0.5/a.ics", "https://[::1]/a.ics", "https://169.254.169.254/latest/meta-data/", "https://100.64.1.1/a.ics"])
def test_ip_literals_that_are_internal_are_refused(url):
    assert code(fetcher(ok), url) == "unsafe_address"


def test_the_connection_goes_to_the_checked_address_with_the_original_host_name():
    seen = []
    def handler(request):
        seen.append(request)
        return ok(request)
    fetch(fetcher(handler, "93.184.216.34"))
    assert seen[0].url.host == "93.184.216.34" and seen[0].headers["host"] == "calendar.example.com"  # no second lookup for an attacker to answer differently
    assert seen[0].url.path == "/private/abcdef-secret-token/basic.ics"


def test_dns_failure_is_a_fixed_code():
    async def failing(host, port):
        raise OSError("name resolution failed for calendar.example.com secret-token")
    f = FeedFetcher(resolver=failing, transport=httpx.MockTransport(ok))
    assert code(f) == "dns_failed"


# --- redirects --------------------------------------------------------------------------------------------------------------------------------------------------

def redirect(location, status=302):
    return lambda request: httpx.Response(status, headers={"location": location})


def test_a_redirect_to_an_internal_literal_is_refused():
    assert code(fetcher(redirect("https://169.254.169.254/latest/meta-data/"))) == "unsafe_address"


def test_a_redirect_to_plain_http_is_refused():
    assert code(fetcher(redirect("http://calendar.example.com/a.ics"))) == "unsafe_url"


def test_a_redirect_to_a_name_that_resolves_internally_is_refused():
    calls = []
    async def resolve(host, port):
        calls.append(host)
        return ["93.184.216.34"] if host == "calendar.example.com" else ["10.0.0.9"]
    f = FeedFetcher(resolver=resolve, transport=httpx.MockTransport(redirect("https://evil.example.net/a.ics")))
    assert code(f) == "unsafe_address" and calls == ["calendar.example.com", "evil.example.net"]


def test_a_redirect_to_another_public_https_host_is_followed_and_rechecked():
    def handler(request):
        if request.headers["host"] == "calendar.example.com":
            return httpx.Response(301, headers={"location": "https://cdn.example.org/feed.ics"})
        return ok(request)
    assert fetch(fetcher(handler)).body == CALENDAR


def test_a_redirect_loop_ends():
    assert code(fetcher(redirect("https://calendar.example.com/again"))) == "redirect_refused"


def test_a_redirect_without_a_location_is_refused():
    assert code(fetcher(lambda request: httpx.Response(302))) == "redirect_refused"


# --- the response ----------------------------------------------------------------------------------------------------------------------------------------------

def test_a_good_feed_downloads():
    result = fetch(fetcher(ok))
    assert result.body == CALENDAR


def test_http_errors_are_a_code_with_the_status_only():
    assert code(fetcher(lambda r: httpx.Response(404, content=b"secret-token not found"))) == "http_404"
    assert code(fetcher(lambda r: httpx.Response(503))) == "http_503"


def test_not_a_calendar_is_refused():
    assert code(fetcher(lambda r: httpx.Response(200, content=b"<html>login secret-token</html>"))) == "not_calendar"


def test_an_oversized_feed_is_refused_by_declared_and_by_actual_size():
    assert code(fetcher(lambda r: httpx.Response(200, content=CALENDAR, headers={"content-length": str(50_000_000)}), max_bytes=1000)) == "too_large"
    big = b"BEGIN:VCALENDAR\r\n" + b"X-FILLER:aaaa\r\n" * 5000
    assert code(fetcher(lambda r: httpx.Response(200, content=big), max_bytes=1000)) == "too_large"


def test_transport_errors_are_a_fixed_code():
    def boom(request):
        raise httpx.ConnectError("could not connect to https://calendar.example.com/private/abcdef-secret-token/basic.ics")
    assert code(fetcher(boom)) == "connect_failed"
    def slow(request):
        raise httpx.ReadTimeout("timed out reading secret-token")
    assert code(fetcher(slow)) == "timeout"


def test_check_validates_without_downloading_and_returns_only_the_host():
    called = []
    f = fetcher(lambda request: called.append(1) or ok(request))
    assert asyncio.run(f.check(SECRET_URL)) == "calendar.example.com" and not called
    with pytest.raises(FeedError):
        asyncio.run(fetcher(ok, "10.0.0.1").check(SECRET_URL))


def test_the_testing_switch_allows_a_local_http_fixture_and_nothing_else_changes():
    local = FeedFetcher(resolver=resolver("127.0.0.1"), transport=httpx.MockTransport(ok), allow_local=True)
    assert fetch(local, "http://127.0.0.1:8099/work.ics").body == CALENDAR
    assert code(fetcher(ok), "http://127.0.0.1:8099/work.ics") == "unsafe_url"  # off by default
