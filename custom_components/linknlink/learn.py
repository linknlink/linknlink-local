"""Learning helpers for LinknLink IR/RF capture.

These are used by both the remote entity and the config subentry flow.
They are deliberately free of Home Assistant imports so they can be
unit-tested standalone; ``coordinator`` only needs ``async_request`` and
an ``api`` with the LinknLink learning methods.
"""
from __future__ import annotations

import asyncio
from base64 import b64encode

from linknlink.exceptions import ReadError, StorageError

LEARNING_TIMEOUT = 30.0
POLL_INTERVAL = 1.0


async def _async_poll_code(
    coordinator,
    timeout: float,
    poll_interval: float,
    signal_name: str,
) -> str:
    """Poll the device for a captured code and return it base64-encoded."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        await asyncio.sleep(poll_interval)
        try:
            code = await coordinator.async_request(coordinator.api.check_data)
        except (ReadError, StorageError):
            continue
        return b64encode(code).decode("utf8")
    raise TimeoutError(
        f"No {signal_name} code received within {timeout} seconds"
    )


async def async_learn_ir(
    coordinator,
    timeout: float = LEARNING_TIMEOUT,
    poll_interval: float = POLL_INTERVAL,
) -> str:
    """Capture an infrared code. The user must press the button once."""
    await coordinator.async_request(coordinator.api.enter_learning)
    return await _async_poll_code(coordinator, timeout, poll_interval, "infrared")


async def async_sweep_rf(
    coordinator,
    timeout: float = LEARNING_TIMEOUT,
    poll_interval: float = POLL_INTERVAL,
) -> None:
    """Sweep for the RF frequency. The user must press and hold the button.

    Raises TimeoutError if no frequency is found; the sweep is cancelled
    on the device before raising.
    """
    await coordinator.async_request(coordinator.api.sweep_frequency)
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        await asyncio.sleep(poll_interval)
        if await coordinator.async_request(coordinator.api.check_frequency):
            return
    await coordinator.async_request(coordinator.api.cancel_sweep_frequency)
    raise TimeoutError(f"No radiofrequency found within {timeout} seconds")


async def async_learn_rf(
    coordinator,
    timeout: float = LEARNING_TIMEOUT,
    poll_interval: float = POLL_INTERVAL,
) -> str:
    """Capture an RF code after a successful sweep.

    The user must press the button again (a short press this time).
    """
    await coordinator.async_request(coordinator.api.find_rf_packet)
    return await _async_poll_code(
        coordinator, timeout, poll_interval, "radiofrequency"
    )
