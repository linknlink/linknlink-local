"""Radio frequency transmitter platform for LinknLink devices.

Exposes the device as a transmitter for the Home Assistant ``radio_frequency``
platform introduced in HA 2026.5, so consumer integrations can send RF
commands through this hardware via ``radio_frequency.async_send_command``.

The hardware supports OOK at 315 MHz and 433 MHz only. We advertise both
bands; ``codec.encode_rf`` selects the correct wire-format header byte.
"""
from __future__ import annotations

import logging

from linknlink.exceptions import LinknLinkException

from homeassistant.components.radio_frequency import (
    ModulationType,
    RadioFrequencyCommand,
    RadioFrequencyTransmitterEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import codec
from .const import DOMAIN
from .coordinator import LinknLinkCoordinator
from .entity import LinknLinkEntity

_LOGGER = logging.getLogger(__name__)

SUPPORTED_FREQUENCY_RANGES: list[tuple[int, int]] = [
    (315_000_000, 315_000_000),
    (433_050_000, 434_790_000),
]


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the LinknLink radio frequency transmitter."""
    coordinator: LinknLinkCoordinator = hass.data[DOMAIN][config_entry.entry_id]
    if not hasattr(coordinator.api, "sweep_frequency"):
        # Hardware reports no RF capability; skip exposing a transmitter.
        return
    async_add_entities(
        [LinknLinkRadioFrequencyTransmitter(coordinator)], False
    )


class LinknLinkRadioFrequencyTransmitter(LinknLinkEntity, RadioFrequencyTransmitterEntity):
    """LinknLink RF transmitter exposed to the HA radio_frequency platform."""

    _attr_name = "Radio frequency"
    _attr_supported_frequency_ranges = SUPPORTED_FREQUENCY_RANGES

    def __init__(self, coordinator: LinknLinkCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.api.mac.hex()}-radio-frequency"

    @property
    def supported_frequency_ranges(self) -> list[tuple[int, int]]:
        return SUPPORTED_FREQUENCY_RANGES

    async def async_send_command(self, command: RadioFrequencyCommand) -> None:
        if command.modulation is not ModulationType.OOK:
            raise HomeAssistantError(
                f"Unsupported modulation {command.modulation!r}; "
                "LinknLink hardware is OOK-only"
            )
        timings = list(command.get_raw_timings())
        if not timings:
            raise HomeAssistantError("Radio frequency command has no timings")
        try:
            blob = codec.encode_rf(timings, frequency_hz=command.frequency)
        except ValueError as err:
            raise HomeAssistantError(str(err)) from err
        try:
            await self.coordinator.async_request(
                self.coordinator.api.send_data, blob
            )
        except (LinknLinkException, OSError) as err:
            raise HomeAssistantError(
                f"Failed to send radio frequency command: {err}"
            ) from err
