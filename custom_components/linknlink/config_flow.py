"""Config flow for linknlink devices."""
import asyncio
import errno
from functools import partial
import logging
import socket
from typing import Any

import linknlink as llk
from linknlink.exceptions import (
    AuthenticationError,
    LinknLinkException,
    NetworkTimeoutError,
)
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.components import dhcp
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigSubentryFlow,
    SubentryFlowResult,
)
from homeassistant.const import CONF_HOST, CONF_MAC, CONF_NAME, CONF_TIMEOUT, CONF_TYPE
from homeassistant.core import callback
from homeassistant.data_entry_flow import AbortFlow, FlowResult
from homeassistant.helpers import config_validation as cv

from . import learn
from .const import (
    COMMAND_TYPE_IR,
    COMMAND_TYPE_RF,
    CONF_COMMAND_TYPE,
    CONF_COMMANDS,
    DEFAULT_TIMEOUT,
    DEVICE_TYPES,
    DOMAIN,
    SUBENTRY_TYPE_DEVICE,
)
from .coordinator import LinknLinkCoordinator
from .helpers import data_packet

_LOGGER = logging.getLogger(__name__)

CONF_CODE = "code"
CONF_REMOVE = "remove"


class linknlinkFlowHandler(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a linknlink config flow."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the linknlink flow."""
        self.device: llk.Device = None

    @classmethod
    @callback
    def async_get_supported_subentry_types(
        cls, config_entry: ConfigEntry
    ) -> dict[str, type[ConfigSubentryFlow]]:
        """Return subentry types supported by this integration."""
        return {SUBENTRY_TYPE_DEVICE: ControlledDeviceSubentryFlowHandler}

    async def async_set_device(self, device: llk.Device, raise_on_progress=True):
        """Define a device for the config flow."""
        if device.type not in DEVICE_TYPES:
            _LOGGER.error(
                ("Unsupported device: %s"),
                hex(device.devtype),
            )
            raise AbortFlow("not_supported")

        await self.async_set_unique_id(
            device.mac.hex(), raise_on_progress=raise_on_progress
        )
        self.device = device

        self.context["title_placeholders"] = {
            "name": device.name,
            "model": device.model,
            "host": device.host[0],
        }

    async def async_step_dhcp(self, discovery_info: dhcp.DhcpServiceInfo) -> FlowResult:
        """Handle dhcp discovery."""
        host = discovery_info.ip
        unique_id = discovery_info.macaddress.lower().replace(":", "")
        await self.async_set_unique_id(unique_id)
        self._abort_if_unique_id_configured(updates={CONF_HOST: host})
        try:
            device = await self.hass.async_add_executor_job(llk.hello, host)

        except NetworkTimeoutError:
            return self.async_abort(reason="cannot_connect")

        except OSError as err:
            if err.errno == errno.ENETUNREACH:
                return self.async_abort(reason="cannot_connect")
            return self.async_abort(reason="unknown")

        if device.type not in DEVICE_TYPES:
            return self.async_abort(reason="not_supported")

        await self.async_set_device(device)
        return await self.async_step_auth()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle a flow initiated by the user."""
        errors = {}

        if user_input:
            host = user_input[CONF_HOST]
            timeout = user_input.get(CONF_TIMEOUT, DEFAULT_TIMEOUT)

            try:
                hello = partial(llk.hello, host, timeout=timeout)
                linknlink = await self.hass.async_add_executor_job(hello)

            except NetworkTimeoutError:
                errors["base"] = "cannot_connect"
                err_msg = "Device not found"

            except OSError as err:
                if err.errno in {errno.EINVAL, socket.EAI_NONAME}:
                    errors["base"] = "invalid_host"
                    err_msg = "Invalid hostname or IP address"
                elif err.errno == errno.ENETUNREACH:
                    errors["base"] = "cannot_connect"
                    err_msg = str(err)
                else:
                    errors["base"] = "unknown"
                    err_msg = str(err)

            else:
                linknlink.timeout = timeout

                await self.async_set_device(linknlink)
                self._abort_if_unique_id_configured(
                    updates={CONF_HOST: linknlink.host[0], CONF_TIMEOUT: timeout}
                )
                return await self.async_step_auth()

            _LOGGER.error("Failed to connect to the device at %s: %s", host, err_msg)

        data_schema = {
            vol.Required(CONF_HOST): str,
            vol.Optional(CONF_TIMEOUT, default=DEFAULT_TIMEOUT): cv.positive_int,
        }
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(data_schema),
            errors=errors,
        )

    async def async_step_auth(self) -> FlowResult:
        """Authenticate to the device."""
        device = self.device
        errors = {}

        try:
            await self.hass.async_add_executor_job(device.auth)

        except AuthenticationError:
            errors["base"] = "invalid_auth"
            await self.async_set_unique_id(device.mac.hex())
            return await self.async_step_reset(errors=errors)

        except NetworkTimeoutError as err:
            errors["base"] = "cannot_connect"
            err_msg = str(err)

        except LinknLinkException as err:
            errors["base"] = "unknown"
            err_msg = str(err)

        except OSError as err:
            if err.errno == errno.ENETUNREACH:
                errors["base"] = "cannot_connect"
                err_msg = str(err)
            else:
                errors["base"] = "unknown"
                err_msg = str(err)

        else:
            await self.async_set_unique_id(device.mac.hex())
            if device.is_locked:
                return await self.async_step_unlock()
            return await self.async_finish()

        await self.async_set_unique_id(device.mac.hex())
        _LOGGER.error(
            "Failed to authenticate to the device at %s: %s", device.host[0], err_msg
        )
        return self.async_show_form(step_id="auth", errors=errors)

    async def async_step_reset(self, user_input=None, errors=None) -> FlowResult:
        """Guide the user to unlock the device manually.

        We are unable to authenticate because the device is locked.
        The user needs to open the LinknLink app and unlock the device.
        """
        device = self.device

        if user_input is None:
            return self.async_show_form(
                step_id="reset",
                errors=errors,
                description_placeholders={
                    "name": device.name,
                    "model": device.model,
                    "host": device.host[0],
                },
            )

        return await self.async_step_user(
            {CONF_HOST: device.host[0], CONF_TIMEOUT: device.timeout}
        )

    async def async_step_unlock(self, user_input=None) -> FlowResult:
        """Unlock the device.

        The authentication succeeded, but the device is locked.
        We can offer an unlock to prevent authorization errors.
        """
        device = self.device
        errors = {}

        if user_input is None:
            pass

        elif user_input["unlock"]:
            try:
                await self.hass.async_add_executor_job(device.set_lock, False)

            except NetworkTimeoutError as err:
                errors["base"] = "cannot_connect"
                err_msg = str(err)

            except LinknLinkException as err:
                errors["base"] = "unknown"
                err_msg = str(err)

            except OSError as err:
                if err.errno == errno.ENETUNREACH:
                    errors["base"] = "cannot_connect"
                    err_msg = str(err)
                else:
                    errors["base"] = "unknown"
                    err_msg = str(err)

            else:
                return await self.async_finish()

            _LOGGER.error(
                "Failed to unlock the device at %s: %s", device.host[0], err_msg
            )

        else:
            return await self.async_finish()

        data_schema = {vol.Required("unlock", default=False): bool}
        return self.async_show_form(
            step_id="unlock",
            errors=errors,
            data_schema=vol.Schema(data_schema),
            description_placeholders={
                "name": device.name,
                "model": device.model,
                "host": device.host[0],
            },
        )

    async def async_finish(self) -> FlowResult:
        """Create config entry."""
        device = self.device

        # Abort reauthentication flow.
        self._abort_if_unique_id_configured(
            updates={CONF_HOST: device.host[0], CONF_TIMEOUT: device.timeout}
        )

        return self.async_create_entry(
            title=f"{DOMAIN}-{device.mac.hex()}",
            data={
                CONF_HOST: device.host[0],
                CONF_MAC: device.mac.hex(),
                CONF_TYPE: device.devtype,
                CONF_TIMEOUT: device.timeout,
            },
        )

class ControlledDeviceSubentryFlowHandler(ConfigSubentryFlow):
    """Manage an IR/RF-controlled appliance as a config subentry.

    Lets the user add appliances from the UI, learn commands with live
    progress dialogs, paste base64 codes manually, and remove commands
    on reconfigure. One button entity is created per learned command.
    """

    def __init__(self) -> None:
        """Initialize the subentry flow."""
        self._name: str | None = None
        self._command_type: str = COMMAND_TYPE_IR
        self._commands: dict[str, str] = {}
        self._pending_command: str | None = None
        self._learn_task: asyncio.Task | None = None
        self._sweep_task: asyncio.Task | None = None

    def _get_coordinator(self) -> LinknLinkCoordinator:
        """Return the coordinator of the parent config entry."""
        entry = self._get_entry()
        coordinator = self.hass.data.get(DOMAIN, {}).get(entry.entry_id)
        if coordinator is None:
            raise AbortFlow("not_loaded")
        return coordinator

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Ask for the appliance name and command type."""
        if user_input is not None:
            self._name = user_input[CONF_NAME]
            self._command_type = user_input[CONF_COMMAND_TYPE]
            return await self.async_step_menu()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_NAME): str,
                    vol.Required(
                        CONF_COMMAND_TYPE, default=COMMAND_TYPE_IR
                    ): vol.In([COMMAND_TYPE_IR, COMMAND_TYPE_RF]),
                }
            ),
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Start reconfiguration of an existing appliance."""
        subentry = self._get_reconfigure_subentry()
        self._name = subentry.title
        self._command_type = subentry.data.get(CONF_COMMAND_TYPE, COMMAND_TYPE_IR)
        self._commands = dict(subentry.data.get(CONF_COMMANDS, {}))
        return await self.async_step_menu()

    async def async_step_menu(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Show the command management menu."""
        options = ["learn", "manual"]
        if self._commands:
            options.append("remove")
        options.append("finish")
        return self.async_show_menu(
            step_id="menu",
            menu_options=options,
            description_placeholders={
                "name": self._name or "",
                "count": str(len(self._commands)),
            },
        )

    async def async_step_learn(
        self, user_input: dict[str, Any] | None = None, errors: dict | None = None
    ) -> SubentryFlowResult:
        """Ask for the name of the command to learn."""
        if user_input is not None:
            self._pending_command = user_input[CONF_NAME]
            if self._command_type == COMMAND_TYPE_RF:
                return await self.async_step_sweep_rf()
            return await self.async_step_learn_code()

        return self.async_show_form(
            step_id="learn",
            data_schema=vol.Schema({vol.Required(CONF_NAME): str}),
            errors=errors,
        )

    async def async_step_sweep_rf(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Sweep the RF frequency while the user holds the button."""
        if self._sweep_task is None:
            coordinator = self._get_coordinator()
            self._sweep_task = self.hass.async_create_task(
                learn.async_sweep_rf(coordinator)
            )
        if not self._sweep_task.done():
            return self.async_show_progress(
                step_id="sweep_rf",
                progress_action="sweep_rf",
                progress_task=self._sweep_task,
                description_placeholders={"command": self._pending_command or ""},
            )
        return self.async_show_progress_done(next_step_id="sweep_result")

    async def async_step_sweep_result(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Check the sweep result and continue to code capture."""
        task = self._sweep_task
        self._sweep_task = None
        try:
            task.result()
        except TimeoutError:
            return await self.async_step_learn(errors={"base": "sweep_timeout"})
        except (LinknLinkException, OSError) as err:
            _LOGGER.error("Failed to sweep frequency: %s", err)
            return await self.async_step_learn(errors={"base": "learn_failed"})
        return await self.async_step_learn_code()

    async def async_step_learn_code(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Capture the code while the user presses the button."""
        if self._learn_task is None:
            coordinator = self._get_coordinator()
            if self._command_type == COMMAND_TYPE_RF:
                coro = learn.async_learn_rf(coordinator)
            else:
                coro = learn.async_learn_ir(coordinator)
            self._learn_task = self.hass.async_create_task(coro)
        if not self._learn_task.done():
            return self.async_show_progress(
                step_id="learn_code",
                progress_action=f"learn_{self._command_type}",
                progress_task=self._learn_task,
                description_placeholders={"command": self._pending_command or ""},
            )
        return self.async_show_progress_done(next_step_id="learn_result")

    async def async_step_learn_result(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Store the learned code or report the failure."""
        task = self._learn_task
        self._learn_task = None
        try:
            code = task.result()
        except TimeoutError:
            return await self.async_step_learn(errors={"base": "learn_timeout"})
        except (LinknLinkException, OSError) as err:
            _LOGGER.error("Failed to learn command: %s", err)
            return await self.async_step_learn(errors={"base": "learn_failed"})
        self._commands[self._pending_command] = code
        self._pending_command = None
        return await self.async_step_menu()

    async def async_step_manual(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Add a command from a base64 code pasted by the user."""
        errors = {}
        if user_input is not None:
            code = user_input[CONF_CODE].removeprefix("b64:").strip()
            try:
                data_packet(code)
            except (vol.Invalid, ValueError):  # binascii.Error is a ValueError
                errors["base"] = "invalid_code"
            else:
                self._commands[user_input[CONF_NAME]] = code
                return await self.async_step_menu()

        return self.async_show_form(
            step_id="manual",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_NAME): str,
                    vol.Required(CONF_CODE): str,
                }
            ),
            errors=errors,
        )

    async def async_step_remove(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Remove commands from the appliance."""
        if user_input is not None:
            for command in user_input[CONF_REMOVE]:
                self._commands.pop(command, None)
            return await self.async_step_menu()

        return self.async_show_form(
            step_id="remove",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_REMOVE, default=[]): cv.multi_select(
                        sorted(self._commands)
                    ),
                }
            ),
        )

    async def async_step_finish(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Create or update the subentry."""
        data = {
            CONF_COMMAND_TYPE: self._command_type,
            CONF_COMMANDS: self._commands,
        }
        if self.source == config_entries.SOURCE_RECONFIGURE:
            return self.async_update_and_abort(
                self._get_entry(),
                self._get_reconfigure_subentry(),
                data=data,
            )
        return self.async_create_entry(title=self._name, data=data)
