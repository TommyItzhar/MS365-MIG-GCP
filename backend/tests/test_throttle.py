"""Tests for ThrottleManager — 429 handling, backoff, adaptive throughput."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.throttle.throttle_manager import ThrottleManager, _WorkloadState
from app.models import WorkloadType
from app.constants import MAX_RETRY_ATTEMPTS


class TestWorkloadState:
    def test_adaptive_multiplier_increases_on_high_throttle_rate(self):
        state = _WorkloadState(max_concurrent=4)
        # Record 20 throttled responses (100% throttle rate)
        for _ in range(20):
            state.record_result(throttled=True)
        assert state.adaptive_multiplier > 1.0

    def test_adaptive_multiplier_decreases_on_zero_throttle(self):
        state = _WorkloadState(max_concurrent=4)
        # First spike the multiplier
        for _ in range(20):
            state.record_result(throttled=True)
        multiplier_after_spike = state.adaptive_multiplier

        # Then 20 clean responses
        for _ in range(20):
            state.record_result(throttled=False)
        assert state.adaptive_multiplier <= multiplier_after_spike

    def test_initial_multiplier_is_one(self):
        state = _WorkloadState(max_concurrent=4)
        assert state.adaptive_multiplier == 1.0


@pytest.mark.asyncio
class TestThrottleManager:
    async def test_successful_call_passes_through(self):
        manager = ThrottleManager()
        called_with = []

        async def _fn(x):
            called_with.append(x)
            return x * 2

        result = await manager.execute(WorkloadType.EXCHANGE, _fn, 5)
        assert result == 10
        assert called_with == [5]

    async def test_retries_on_429_then_succeeds(self):
        manager = ThrottleManager()
        attempt = [0]

        async def _fn():
            attempt[0] += 1
            if attempt[0] < 3:
                response = MagicMock()
                response.status_code = 429
                response.headers = {"Retry-After": "0"}
                raise httpx.HTTPStatusError("429", request=MagicMock(), response=response)
            return "success"

        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await manager.execute(WorkloadType.EXCHANGE, _fn)
        assert result == "success"
        assert attempt[0] == 3

    async def test_raises_after_max_retries(self):
        manager = ThrottleManager()

        async def _always_429():
            response = MagicMock()
            response.status_code = 429
            response.headers = {"Retry-After": "0"}
            raise httpx.HTTPStatusError("429", request=MagicMock(), response=response)

        with patch("asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(RuntimeError, match="Max retries"):
                await manager.execute(WorkloadType.EXCHANGE, _always_429)

    async def test_non_retryable_status_propagates_immediately(self):
        manager = ThrottleManager()
        attempt = [0]

        async def _fn():
            attempt[0] += 1
            response = MagicMock()
            response.status_code = 400
            raise httpx.HTTPStatusError("400", request=MagicMock(), response=response)

        with pytest.raises(httpx.HTTPStatusError):
            await manager.execute(WorkloadType.EXCHANGE, _fn)
        assert attempt[0] == 1  # No retries for 400

    def test_parse_retry_after_numeric(self):
        manager = ThrottleManager()
        state = _WorkloadState(max_concurrent=4)
        response = MagicMock()
        response.headers = {"Retry-After": "42"}
        delay = manager._compute_delay(attempt=0, state=state, response=response)
        assert delay == 42.0

    def test_semaphore_limits_concurrency(self):
        manager = ThrottleManager()
        assert manager.get_semaphore_count(WorkloadType.EXCHANGE) == 4
        assert manager.get_semaphore_count(WorkloadType.TEAMS) == 2
        assert manager.get_semaphore_count(WorkloadType.ONEDRIVE) == 8
