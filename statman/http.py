"""Felles HTTP-klient med rate limiting.

Ligger her og ikke i den enkelte konnektoren fordi grensene er per API, og
fordi det er billigere å ha throttlingen på plass fra dag én enn å bli
blokkert og lure på hvorfor.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import Any, Final

DEFAULT_TIMEOUT: Final[float] = 60.0
USER_AGENT: Final[str] = "statman/0.1 (personlig statistikkprosjekt)"


class RateLimiter:
    """Enkel glidende vindu-throttle. Trådsikker."""

    def __init__(self, max_calls: int, per_seconds: float) -> None:
        if max_calls < 1:
            raise ValueError("max_calls må være minst 1")
        self.max_calls = max_calls
        self.per_seconds = per_seconds
        self._calls: deque[float] = deque()
        self._lock = threading.Lock()

    def acquire(self, *, _sleep: Any = time.sleep, _now: Any = time.monotonic) -> float:
        """Blokker til det er lov å gjøre et kall. Returnerer ventetiden."""
        waited = 0.0
        while True:
            with self._lock:
                now = _now()
                while self._calls and now - self._calls[0] >= self.per_seconds:
                    self._calls.popleft()
                if len(self._calls) < self.max_calls:
                    self._calls.append(now)
                    return waited
                sleep_for = self.per_seconds - (now - self._calls[0])
            sleep_for = max(sleep_for, 0.001)
            _sleep(sleep_for)
            waited += sleep_for


def get(
    url: str,
    *,
    params: dict[str, str] | None = None,
    limiter: RateLimiter | None = None,
    timeout: float = DEFAULT_TIMEOUT,
    headers: dict[str, str] | None = None,
) -> Any:
    """GET med throttle. Returnerer httpx.Response, og reiser ved 4xx/5xx."""
    import httpx

    if limiter is not None:
        limiter.acquire()
    response = httpx.get(
        url,
        params=params,
        timeout=timeout,
        follow_redirects=True,
        headers={"User-Agent": USER_AGENT, **(headers or {})},
    )
    response.raise_for_status()
    return response
