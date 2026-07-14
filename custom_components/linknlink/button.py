"""Button entities for IR/RF commands learned via config subentries.

Each ``controlled_device`` subentry represents an appliance (TV, fan,
garage door, ...) and creates one button per learned command. The
entities are registered against the subentry so Home Assistant removes
them automatically when the appliance is deleted from the UI.
"""
from __future__ import annotations

import logging

from linknlink.exceptions import LinknLinkException

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    COMMAND_TYPE_IR,
    CONF_COMMAND_TYPE,
    CONF_COMMANDS,
    DOMAIN,
    SUBENTRY_TYPE_DEVICE,
)
from .coordinator import LinknLinkCoordinator
from .helpers import data_packet

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up buttons for every controlled-device subentry."""
    coordinator: LinknLinkCoordinator = hass.data[DOMAIN][config_entry.entry_id]

    for subentry_id, subentry in config_entry.subentries.items():
        if subentry.subentry_type != SUBENTRY_TYPE_DEVICE:
            continue
        command_type = subentry.data.get(CONF_COMMAND_TYPE, COMMAND_TYPE_IR)
        entities = [
            LinknLinkCommandButton(
                coordinator, subentry_id, subentry.title, command_type, command, code
            )
            for command, code in subentry.data.get(CONF_COMMANDS, {}).items()
        ]
        if entities:
            async_add_entities(entities, config_subentry_id=subentry_id)


class LinknLinkCommandButton(CoordinatorEntity[LinknLinkCoordinator], ButtonEntity):
    """A button that sends one learned IR/RF command."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: LinknLinkCoordinator,
        subentry_id: str,
        appliance_name: str,
        command_type: str,
        command: str,
        code: str,
    ) -> None:
        """Initialize the command button."""
        super().__init__(coordinator)
        self._command = command
        self._code = data_packet(code)
        mac = coordinator.api.mac.hex()
        self._attr_name = command
        self._attr_unique_id = f"{mac}-{subentry_id}-{command}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{mac}-{subentry_id}")},
            name=appliance_name,
            manufacturer="LinknLink",
            model=(
                "Infrared device"
                if command_type == COMMAND_TYPE_IR
                else "Radio frequency device"
            ),
            via_device=(DOMAIN, mac),
        )

    async def async_press(self) -> None:
        """Send the learned command."""
        try:
            await self.coordinator.async_request(
                self.coordinator.api.send_data, self._code
            )
        except (LinknLinkException, OSError) as err:
            raise HomeAssistantError(
                f"Failed to send command '{self._command}': {err}"
            ) from err
