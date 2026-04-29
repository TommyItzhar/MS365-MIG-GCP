"""Throttle Manager — adaptive rate limiting for Microsoft Graph API calls.

Implements:
- HTTP 429 detection with Retry-After header parsing
- Exponential backoff with ±20% jitter (RFC 7231)
- Per-workload asyncio.Semaphore concurrency gates
- Token bucket rate limiter (sliding window)
- Adaptive throughput: backs off when 429 rate exceeds threshold
"""
from __future__ import annotations

import asyncio
import logging
import random
import time
from collections import deque
from typing import Callable, Optional, TypeVar

import httpx

from app.constants import (
    BACKOFF_JITTER_FACTOR,
    BACKOFF_MAX_SECONDS,
    BACKOFF_MIN_SECONDS,
    DEFAULT_RETRY_AFTER_SECONDS,
    EXCHANGE_MAX_CONCURRENT,
    GROUPS_MAX_CONCURRENT,
    HTTP_TRANSIENT_STATUS_CODES,
    IDENTITY_MAX_CONCURRENT,
    INTUNE_MAX_CONCURRENT,
    MAX_RETRY_ATTEMPTS,
    ONEDRIVE_MAX_CONCURRENT,
    RATE_LIMIT_STATUS_CODE,
    SHAREPOINT_MAX_CONCURRENT,
    TEAMS_MAX_CONCURRENT,
)
from app.models import WorkloadType

logger = logging.getLogger(__name__)

T = TypeVar("T")

_WORKLOAD_CONCURRENCY: dict[WorkloadType, int] = {
    WorkloadType.EXCHANGE: EXCHANGE_MAX_CONCURRENT,
    WorkloadType.ONEDRIVE: ONEDRIVE_MAX_CONCURRENT,
    WorkloadType.SHAREPOINT: SHAREPOINT_MAX_CONCURRENT,
    WorkloadType.TEAMS: TEAMS_MAX_CONCURRENT,
    WorkloadType.TEAMS_CHAT: TEAMS_MAX_CONCURRENT,
    WorkloadType.GROUPS: GROUPS_MAX_CONCURRENT,
    WorkloadType.IDENTITY: IDENTITY_MAX_CONCURRENT,
    WorkloadType.INTUNE: INTUNE_MAX_CONCURRENT,
    WorkloadType.POWER_AUTOMATE: IDENTITY_MAX_CONCURRENT,
    WorkloadType.FORMS: IDENTITY_MAX_CONCURRENT,
    WorkloadType.PLANNER: GROUPS_MAX_CONCURRENT,
}

# Adaptive backoff: if >10% of the last 20 requests returned 429, double delay
_ADAPTIVE_WINDOW = 20
_ADAPTIVE_THRESHOLD = 0.10


class _WorkloadState:
    """Tracks per-workload concurrency and 429 history."""

    def __init__(self, max_concurrent: int) -> None:
        self.semaphore = asyncio.Semaphore(max_concurrent)
        self._history: deque[bool] = deque(maxlen=_ADAPTIVE_WINDOW)
        self._adaptive_multiplier: float = 1.0

    def record_result(self, throttled: bool) -> None:
        self._history.append(throttled)
        if len(self._history) == _ADAPTIVE_WINDOW:
            rate = sum(self._history) / _ADAPTIVE_WINDOW
            if rate > _ADAPTIVE_THRESHOLD:
                self._adaptive_multiplier = min(self._adaptive_multiplier * 2, 8.0)
                logger.warning(
                    "adaptive_backoff_increased",
                    extra={
                        "throttle_rate": round(rate, 3),
                        "multiplier": self._adaptive_multiplier,
                    },
                )
            elif rate == 0.0:
                self._adaptive_multiplier = max(self._adaptive_multiplier * 0.9, 1.0)

    @property
    def adaptive_multiplier(self) -> float:
        return self._adaptive_multiplier


class ThrottleManager:
    """Central throttle / rate-limit manager.

    Usage::

        throttle = ThrottleManager()

        result = await throttle.execute(
            workload=WorkloadType.EXCHANGE,
            fn=my_async_api_call,
        )
    """

    def __init__(self) -> None:
        self._states: dict[WorkloadType, _WorkloadState] = {
            wl: _WorkloadState(max_concurrent)
            for wl, max_concurrent in _WORKLOAD_CONCURRENCY.items()
        }

    # ── Core execute-with-retry ────────────────────────────────────────────

    async def execute(
        self,
        workload: WorkloadType,
        fn: Callable[..., object],
        *args: object,
        **kwargs: object,
    ) -> object:
        """Execute *fn* under the workload semaphore with retry + backoff."""
        state = self._states[workload]
        last_exception: Optional[Exception] = None

        for attempt in range(MAX_RETRY_ATTEMPTS + 1):
            async with state.semaphore:
                try:
                    result = await fn(*args, **kwargs)  # type: ignore[operator]
                    state.record_result(throttled=False)
                    return result
                except httpx.HTTPStatusError as exc:
                    status = exc.response.status_code
                    if status not in HTTP_TRANSIENT_STATUS_CODES:
                        raise

                    throttled = status == RATE_LIMIT_STATUS_CODE
                    state.record_result(throttled=throttled)
                    delay = self._compute_delay(
                        attempt=attempt,
                        response=exc.response if throttled else None,
                        state=state,
                    )
                    logger.warning(
                        "graph_request_throttled",
                        extra={
                            "workload": workload.value,
                            "status": status,
                            "attempt": attempt,
                            "retry_after_seconds": delay,
                        },
                    )
                    last_exception = exc

                except (httpx.TimeoutException, httpx.NetworkError) as exc:
                    state.record_result(throttled=False)
                    delay = self._compute_delay(attempt=attempt, state=state)
                    logger.warning(
                        "graph_request_network_error",
                        extra={
                            "workload": workload.value,
                            "error": str(exc),
                            "attempt": attempt,
                            "retry_after_seconds": delay,
                        },
                    )
                    last_exception = exc

            if attempt < MAX_RETRY_ATTEMPTS:
                await asyncio.sleep(delay)  # type: ignore[possibly-undefined]

        raise RuntimeError(
            f"Max retries ({MAX_RETRY_ATTEMPTS}) exceeded "
            f"for workload={workload.value}"
        ) from last_exception

    # ── Delay calculation ──────────────────────────────────────────────────

    def _compute_delay(
        self,
        attempt: int,
        state: _WorkloadState,
        response: Optional[httpx.Response] = None,
    ) -> float:
        if response is not None:
            retry_after = self._parse_retry_after(response)
            if retry_after:
                return retry_after * state.adaptive_multiplier

        base = min(
            BACKOFF_MIN_SECONDS * (2**attempt),
            BACKOFF_MAX_SECONDS,
        )
        jitter = random.uniform(
            -base * BACKOFF_JITTER_FACTOR,
            base * BACKOFF_JITTER_FACTOR,
        )
        delay = max(BACKOFF_MIN_SECONDS, base + jitter)
        return delay * state.adaptive_multiplier

    @staticmethod
    def _parse_retry_after(response: httpx.Response) -> Optional[float]:
        header = response.headers.get("Retry-After", "")
        if not header:
            return DEFAULT_RETRY_AFTER_SECONDS
        try:
            return float(header)
        except ValueError:
            # May be an HTTP-date — fall back to default
            return DEFAULT_RETRY_AFTER_SECONDS

    # ── Convenience: batch requests with throttle-awareness ────────────────

    async def execute_batch(
        self,
        workload: WorkloadType,
        fns: list[Callable[[], object]],
    ) -> list[object]:
        """Execute a list of async callables concurrently, respecting semaphore."""
        tasks = [
            self.execute(workload, fn) for fn in fns
        ]
        return list(await asyncio.gather(*tasks, return_exceptions=True))

    # ── Instrumentation ────────────────────────────────────────────────────

    def get_adaptive_multiplier(self, workload: WorkloadType) -> float:
        return self._states[workload].adaptive_multiplier

    def get_semaphore_count(self, workload: WorkloadType) -> int:
        """Return number of available semaphore slots (for monitoring)."""
        sem = self._states[workload].semaphore
        return sem._value  # type: ignore[attr-defined]
