"""Small standard-library client for the Telegram Bot API."""

import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class TelegramError(RuntimeError):
    """A Telegram request failed without exposing the bot token."""

    def __init__(self, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.retryable = retryable


class TelegramAPI:
    def __init__(self, token: str) -> None:
        self._base_url = f"https://api.telegram.org/bot{token}/"

    def call(self, method: str, **parameters):
        body = json.dumps(parameters).encode("utf-8")
        request = Request(
            self._base_url + method,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=40) as response:
                payload = json.load(response)
        except HTTPError as exc:
            try:
                error = json.load(exc)
                description = error.get("description", "Telegram rejected the request")
            except (ValueError, OSError):
                description = "Telegram rejected the request"
            raise TelegramError(
                f"{method}: {description} (HTTP {exc.code})",
                retryable=exc.code == 429 or exc.code >= 500,
            ) from None
        except URLError as exc:
            raise TelegramError(
                f"{method}: network connection failed", retryable=True
            ) from None
        if not payload.get("ok"):
            code = payload.get("error_code", 0)
            raise TelegramError(
                f"{method}: {payload.get('description', 'unknown API error')}",
                retryable=code == 429 or code >= 500,
            )
        return payload["result"]
