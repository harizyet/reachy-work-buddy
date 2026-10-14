"""Weather for the Home dashboard (docs/phase-51.md): current conditions and today's forecast for the owner's configured location, from Open-Meteo.

Every number comes from the provider and is shown as it came; no language model touches it. The adapter is the only thing in core that calls the provider, and Home never waits on it
for anything else: a failure, a timeout or a missing location becomes a fixed status for the weather section alone. Results are cached for a configurable time; when a refresh fails
the last good answer is still shown, labelled stale, until it is too old to be useful.

The provider is queried with a place name (the persona's free-text location) and the persona's timezone, nothing else about the owner. Open-Meteo's free service needs no key and is for
non-commercial use; its attribution (CC BY 4.0) travels with every answer.
"""

from __future__ import annotations

import asyncio
import logging
import math
import os
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import httpx

log = logging.getLogger(__name__)

ENABLED_ENV = "WEATHER_ENABLED"  # default on; "false" turns the adapter off and the section says so
CACHE_ENV = "WEATHER_CACHE_MINUTES"  # how long a good answer is reused (default 30, 1 to 360)
TIMEOUT_ENV = "WEATHER_TIMEOUT_SECONDS"  # per provider call (default 5, 1 to 30)
STALE_ENV = "WEATHER_STALE_HOURS"  # how long a failed refresh may keep showing the last answer, labelled stale (default 6, 1 to 48)
FORECAST_URL_ENV = "WEATHER_FORECAST_URL"
GEOCODE_URL_ENV = "WEATHER_GEOCODE_URL"
LATITUDE_ENV = "WEATHER_LATITUDE"  # optional pair: skips the place-name lookup
LONGITUDE_ENV = "WEATHER_LONGITUDE"

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
ATTRIBUTION = {"name": "Open-Meteo.com", "url": "https://open-meteo.com/", "license": "CC BY 4.0"}
UNITS = {"temperature": "°C", "precipitation": "mm", "wind": "km/h", "humidity": "%", "probability": "%"}

_CURRENT = "temperature_2m,apparent_temperature,relative_humidity_2m,precipitation,weather_code,wind_speed_10m,is_day"
_DAILY = "weather_code,temperature_2m_max,temperature_2m_min,precipitation_sum,precipitation_probability_max,sunrise,sunset"

# WMO weather interpretation codes, as Open-Meteo documents them. Looked up, never generated.
WMO = {
    0: "Clear sky", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast", 45: "Fog", 48: "Rime fog",
    51: "Light drizzle", 53: "Drizzle", 55: "Heavy drizzle", 56: "Light freezing drizzle", 57: "Freezing drizzle",
    61: "Light rain", 63: "Rain", 65: "Heavy rain", 66: "Light freezing rain", 67: "Freezing rain",
    71: "Light snow", 73: "Snow", 75: "Heavy snow", 77: "Snow grains", 80: "Light rain showers", 81: "Rain showers", 82: "Violent rain showers",
    85: "Light snow showers", 86: "Snow showers", 95: "Thunderstorm", 96: "Thunderstorm with hail", 99: "Thunderstorm with heavy hail",
}
_WET = {51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82, 95, 96, 99}


class WeatherError(Exception):
    """`code` is a fixed word; the provider's body and URL never appear in it."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _number(value, low: float, high: float) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not low <= value <= high:
        return None
    return float(value)


def _env_number(name: str, default: float, low: float, high: float) -> float:
    try:
        return min(high, max(low, float(os.environ.get(name, default))))
    except ValueError:
        return default


def enabled() -> bool:
    return os.environ.get(ENABLED_ENV, "true").strip().lower() not in {"0", "false", "no", "off"}


class WeatherService:
    def __init__(
        self, *, transport: httpx.AsyncBaseTransport | None = None, clock=lambda: datetime.now(UTC), cache_seconds: float | None = None, timeout: float | None = None,
        stale_seconds: float | None = None, forecast_url: str | None = None, geocode_url: str | None = None, is_enabled: bool | None = None,
    ) -> None:
        self._transport = transport
        self._clock = clock
        self.cache_seconds = cache_seconds if cache_seconds is not None else _env_number(CACHE_ENV, 30, 1, 360) * 60
        self.timeout = timeout if timeout is not None else _env_number(TIMEOUT_ENV, 5, 1, 30)
        self.stale_seconds = stale_seconds if stale_seconds is not None else _env_number(STALE_ENV, 6, 1, 48) * 3600
        self.forecast_url = forecast_url or os.environ.get(FORECAST_URL_ENV) or FORECAST_URL
        self.geocode_url = geocode_url or os.environ.get(GEOCODE_URL_ENV) or GEOCODE_URL
        self.enabled = enabled() if is_enabled is None else is_enabled
        self._places: dict[str, tuple[float, float, str]] = {}
        self._good: dict[tuple[str, str], tuple[datetime, dict]] = {}
        self._lock = asyncio.Lock()  # one provider call at a time: two screens refreshing together make one request

    # -- the section -------------------------------------------------------------------------------------------------------

    async def section(self, location: str | None, timezone: str) -> dict:
        """The weather section of the Home snapshot. Never raises."""
        if not self.enabled:
            return {"status": "off"}
        if not location and not self._fixed_point():
            return {"status": "not_configured", "detail": "no_location"}
        key = (location or "", timezone)
        now = self._clock()
        cached = self._good.get(key)
        if cached is not None and (now - cached[0]).total_seconds() <= self.cache_seconds:
            return self._shaped(cached[1], cached[0], now, "ok")
        async with self._lock:
            now = self._clock()
            cached = self._good.get(key)  # another caller may have refreshed while this one waited
            if cached is not None and (now - cached[0]).total_seconds() <= self.cache_seconds:
                return self._shaped(cached[1], cached[0], now, "ok")
            try:
                data = await asyncio.wait_for(self._fetch(location, timezone), timeout=self.timeout * 3)
            except (WeatherError, TimeoutError, httpx.HTTPError, ValueError, KeyError) as exc:
                code = exc.code if isinstance(exc, WeatherError) else "timeout" if isinstance(exc, (TimeoutError, httpx.TimeoutException)) else "unavailable"
                log.warning("weather refresh failed: %s", code)
                if cached is not None and (now - cached[0]).total_seconds() <= self.stale_seconds:
                    return {**self._shaped(cached[1], cached[0], now, "stale"), "error": code}
                return {"status": "unavailable", "error": code, "attribution": ATTRIBUTION}
            fetched = self._clock()
            self._good[key] = (fetched, data)
            return self._shaped(data, fetched, fetched, "ok")

    @staticmethod
    def _shaped(data: dict, fetched_at: datetime, now: datetime, status: str) -> dict:
        age = max(0, int((now - fetched_at).total_seconds()))
        return {"status": status, **data, "fetched_at": fetched_at.isoformat(), "age_seconds": age, "attribution": ATTRIBUTION, "units": UNITS}

    # -- the provider ------------------------------------------------------------------------------------------------------

    def _fixed_point(self) -> tuple[float, float] | None:
        lat = _number(_float_or_none(os.environ.get(LATITUDE_ENV)), -90, 90)
        lon = _number(_float_or_none(os.environ.get(LONGITUDE_ENV)), -180, 180)
        return (lat, lon) if lat is not None and lon is not None else None

    async def _get(self, url: str, params: dict) -> dict:
        async with httpx.AsyncClient(timeout=self.timeout, transport=self._transport, follow_redirects=False) as client:
            response = await client.get(url, params=params)
        if response.status_code != 200:
            raise WeatherError("provider_error")
        try:
            body = response.json()
        except ValueError:
            raise WeatherError("bad_response") from None
        if not isinstance(body, dict):
            raise WeatherError("bad_response")
        return body

    async def _place(self, location: str | None) -> tuple[float, float, str]:
        fixed = self._fixed_point()
        if fixed is not None:
            return fixed[0], fixed[1], location or "Configured point"
        assert location
        if location in self._places:
            return self._places[location]
        name, _, rest = location.partition(",")
        body = await self._get(self.geocode_url, {"name": name.strip(), "count": 5, "language": "en", "format": "json"})
        results = [r for r in body.get("results") or [] if isinstance(r, dict) and _number(r.get("latitude"), -90, 90) is not None and _number(r.get("longitude"), -180, 180) is not None]
        if not results:
            raise WeatherError("location_not_found")
        hint = rest.strip().casefold()
        chosen = next((r for r in results if hint and hint in " ".join(str(r.get(k, "")) for k in ("country", "country_code", "admin1")).casefold()), results[0])
        place = (float(chosen["latitude"]), float(chosen["longitude"]), str(chosen.get("name") or name.strip())[:80])
        self._places[location] = place
        return place

    async def _fetch(self, location: str | None, timezone: str) -> dict:
        lat, lon, label = await self._place(location)
        body = await self._get(self.forecast_url, {"latitude": lat, "longitude": lon, "current": _CURRENT, "daily": _DAILY, "timezone": timezone, "forecast_days": 1})
        current, daily = body.get("current"), body.get("daily")
        if not isinstance(current, dict) or not isinstance(daily, dict):
            raise WeatherError("bad_response")
        zone = ZoneInfo(timezone)

        def first(key: str):
            value = daily.get(key)
            return value[0] if isinstance(value, list) and value else None

        def local_iso(text) -> str | None:  # the provider's local wall-clock time, made an exact instant with the timezone we asked for
            try:
                return datetime.fromisoformat(str(text)).replace(tzinfo=zone).isoformat()
            except ValueError:
                return None

        now_code = current.get("weather_code")
        day_code = first("weather_code")
        observed = local_iso(current.get("time"))
        if observed is None or _number(current.get("temperature_2m"), -90, 70) is None:
            raise WeatherError("bad_response")
        return {
            "location": label, "timezone": timezone,
            "observed_at": observed,
            "forecast_date": str(first("time") or "")[:10] or None,
            "current": {
                "temperature": _number(current.get("temperature_2m"), -90, 70), "feels_like": _number(current.get("apparent_temperature"), -120, 90),
                "humidity": _number(current.get("relative_humidity_2m"), 0, 100), "wind_speed": _number(current.get("wind_speed_10m"), 0, 500),
                "precipitation": _number(current.get("precipitation"), 0, 1000), "is_day": current.get("is_day") in (1, True),
                "code": now_code if isinstance(now_code, int) else None, "summary": WMO.get(now_code) if isinstance(now_code, int) else None,
                "raining": isinstance(now_code, int) and now_code in _WET,
            },
            "today": {
                "high": _number(first("temperature_2m_max"), -90, 70), "low": _number(first("temperature_2m_min"), -90, 70),
                "precipitation_total": _number(first("precipitation_sum"), 0, 5000), "precipitation_probability": _number(first("precipitation_probability_max"), 0, 100),
                "code": day_code if isinstance(day_code, int) else None, "summary": WMO.get(day_code) if isinstance(day_code, int) else None,
                "sunrise": local_iso(first("sunrise")), "sunset": local_iso(first("sunset")),
            },
        }


def _float_or_none(text) -> float | None:
    try:
        return float(text) if text is not None else None
    except ValueError:
        return None
