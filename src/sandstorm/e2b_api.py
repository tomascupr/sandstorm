"""Shared HTTP client for the E2B webhook API."""

import json
import urllib.error
import urllib.request

E2B_WEBHOOK_API = "https://api.e2b.app/events/webhooks"


class E2BApiError(RuntimeError):
    """Raised when the E2B webhook API returns an error or is unreachable."""

    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


def webhook_request(
    method: str, path: str, api_key: str, data: dict | None = None
) -> dict | list | None:
    """Make a request to the E2B webhook API.

    Raises E2BApiError on HTTP errors or connection failures.
    """
    url = f"{E2B_WEBHOOK_API}{path}"
    headers = {"X-API-Key": api_key, "Content-Type": "application/json"}
    body = json.dumps(data).encode() if data else None
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read()
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")
        raise E2BApiError(f"E2B API returned {exc.code}: {detail}", exc.code) from exc
    except urllib.error.URLError as exc:
        raise E2BApiError(f"Failed to reach E2B API: {exc.reason}") from exc
