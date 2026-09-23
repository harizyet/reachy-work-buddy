from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator


class AccountConfigPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    client_id: str = Field(min_length=1, max_length=512)
    client_secret: str | None = Field(default=None, max_length=4096, repr=False)
    redirect_uri: str = Field(max_length=2048)
    disconnect_existing: bool = False

    @field_validator("redirect_uri")
    @classmethod
    def callback_url(cls, value):
        parsed = urlsplit(value)
        if (parsed.scheme != "https" and not (
            parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1"}
        )) or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("Use a fixed HTTPS callback (HTTP only for loopback development)")
        if parsed.path not in {"/settings/accounts/google/callback", "/hub/settings/accounts/google/callback"}:
            raise ValueError("Callback path must match the direct or proxied account callback")
        return value


class ConnectAccount(BaseModel):
    model_config = ConfigDict(extra="forbid")
    capability: Literal["gmail", "calendar"]


class CalendarSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    calendar_ids: list[str] = Field(max_length=20)


class OAuthCallback(BaseModel):
    model_config = ConfigDict(extra="forbid")
    state: str = Field(min_length=1, max_length=256, repr=False)
    binding: str = Field(min_length=20, max_length=256, repr=False)
    code: str | None = Field(default=None, max_length=4096, repr=False)
    error: str | None = Field(default=None, max_length=256)


class OAuthStart(ConnectAccount):
    binding: str = Field(min_length=20, max_length=256, repr=False)


class OAuthComplete(BaseModel):
    model_config = ConfigDict(extra="forbid")
    binding: str = Field(min_length=20, max_length=256, repr=False)
