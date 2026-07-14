"""Infrared transmitter platform for LinknLink devices.

Exposes the device as an emitter for the Home Assistant ``infrared`` platform
introduced in HA 2026.4, so consumer integrations can send IR commands through
this hardware via ``infrared.async_send_command``.
"""
from __future__ import annotations

import logging

from linknlink.exceptions import LinknLinkException

from homeassistant.components.infrared import InfraredCommand, InfraredEmitterEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import codec
from .const import DOMAIN
from .coordinator import LinknLinkCoordinator
from .entity import LinknLinkEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the LinknLink infrared emitter."""
    coordinator: LinknLinkCoordinator = hass.data[DOMAIN][config_entry.entry_id]
    async_add_entities([LinknLinkInfraredEmitter(coordinator)], False)


class LinknLinkInfraredEmitter(LinknLinkEntity, InfraredEmitterEntity):
    """LinknLink IR transmitter exposed to the HA infrared platform."""

    _attr_name = "Infrared"

    def __init__(self, coordinator: LinknLinkCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.api.mac.hex()}-infrared"

    async def async_send_command(self, command: InfraredCommand) -> None:
        timings = list(command.get_raw_timings())
        if not timings:
            raise HomeAssistantError("Infrared command has no timings")
        blob = codec.encode_ir(timings)
        try:
            await self.coordinator.async_request(
                self.coordinator.api.send_data, blob
            )
        except (LinknLinkException, OSError) as err:
            raise HomeAssistantError(
                f"Failed to send infrared command: {err}"
            ) from err
