"""Tests for the LinknLink learning helpers."""
from __future__ import annotations

import asyncio
from base64 import b64decode
import importlib.util
import pathlib
import sys
import types

import pytest


# Stub the linknlink package so learn.py imports without the dependency.
class ReadError(Exception):
    pass


class StorageError(Exception):
    pass


_exceptions = types.ModuleType("linknlink.exceptions")
_exceptions.ReadError = ReadError
_exceptions.StorageError = StorageError
_linknlink = types.ModuleType("linknlink")
_linknlink.exceptions = _exceptions
sys.modules.setdefault("linknlink", _linknlink)
sys.modules.setdefault("linknlink.exceptions", _exceptions)

LEARN_PATH = (
    pathlib.Path(__file__).resolve().parent.parent
    / "custom_components"
    / "linknlink"
    / "learn.py"
)
spec = importlib.util.spec_from_file_location("linknlink_learn", LEARN_PATH)
learn = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(learn)

FAST = {"timeout": 0.3, "poll_interval": 0.01}


class FakeApi:
    """Records calls; check_data/check_frequency behavior is scripted."""

    def __init__(self, check_data_results=(), check_frequency_results=()):
        self.calls: list[str] = []
        self._check_data = list(check_data_results)
        self._check_frequency = list(check_frequency_results)

    def enter_learning(self):
        self.calls.append("enter_learning")

    def find_rf_packet(self):
        self.calls.append("find_rf_packet")

    def sweep_frequency(self):
        self.calls.append("sweep_frequency")

    def cancel_sweep_frequency(self):
        self.calls.append("cancel_sweep_frequency")

    def check_frequency(self):
        self.calls.append("check_frequency")
        return self._check_frequency.pop(0) if self._check_frequency else False

    def check_data(self):
        self.calls.append("check_data")
        result = self._check_data.pop(0) if self._check_data else ReadError()
        if isinstance(result, Exception):
            raise result
        return result


class FakeCoordinator:
    def __init__(self, api: FakeApi):
        self.api = api

    async def async_request(self, function, *args, **kwargs):
        return function(*args, **kwargs)


def test_learn_ir_returns_b64():
    api = FakeApi(check_data_results=[ReadError(), b"\x26\x00\x01\x00"])
    code = asyncio.run(learn.async_learn_ir(FakeCoordinator(api), **FAST))
    assert b64decode(code) == b"\x26\x00\x01\x00"
    assert api.calls[0] == "enter_learning"


def test_learn_ir_times_out():
    api = FakeApi()  # check_data always raises ReadError
    with pytest.raises(TimeoutError):
        asyncio.run(learn.async_learn_ir(FakeCoordinator(api), **FAST))


def test_sweep_rf_success():
    api = FakeApi(check_frequency_results=[False, True])
    asyncio.run(learn.async_sweep_rf(FakeCoordinator(api), **FAST))
    assert api.calls[0] == "sweep_frequency"
    assert "cancel_sweep_frequency" not in api.calls


def test_sweep_rf_timeout_cancels_sweep():
    api = FakeApi()  # check_frequency always False
    with pytest.raises(TimeoutError):
        asyncio.run(learn.async_sweep_rf(FakeCoordinator(api), **FAST))
    assert api.calls[-1] == "cancel_sweep_frequency"


def test_learn_rf_returns_b64():
    api = FakeApi(check_data_results=[b"\xb2\x00\x02\x00"])
    code = asyncio.run(learn.async_learn_rf(FakeCoordinator(api), **FAST))
    assert b64decode(code) == b"\xb2\x00\x02\x00"
    assert api.calls[0] == "find_rf_packet"


def test_storage_error_is_retried_then_succeeds():
    api = FakeApi(check_data_results=[StorageError(), StorageError(), b"\x26\x01"])
    code = asyncio.run(learn.async_learn_ir(FakeCoordinator(api), **FAST))
    assert b64decode(code) == b"\x26\x01"
