"""Constants for the linknlink integration."""
from homeassistant.const import Platform

DOMAIN = "linknlink"

PLATFORM_INFRARED = "infrared"
PLATFORM_RADIO_FREQUENCY = "radio_frequency"

# Config subentries: appliances controlled through the hub via IR/RF.
SUBENTRY_TYPE_DEVICE = "controlled_device"
CONF_COMMAND_TYPE = "command_type"
CONF_COMMANDS = "commands"
COMMAND_TYPE_IR = "ir"
COMMAND_TYPE_RF = "rf"

DOMAINS_AND_TYPES: dict[str, set[str]] = {
    # Platform.REMOTE: {"EHUB", "EREMOTE"},
    # Platform.SENSOR: {"EHUB", "ETHS", "EREMOTE"},
    # Platform.BINARY_SENSOR: {"EHUB", "EMOTION", "EREMOTE"},
    # Platform.BUTTON: {"EREMOTE"},
    Platform.REMOTE: {"EHUB", "EREMOTE"},
    Platform.SENSOR: {"EHUB", "ETHS"},
    Platform.BINARY_SENSOR: {"EHUB", "EMOTION"},
    Platform.BUTTON: {"EHUB", "EREMOTE"},
    PLATFORM_INFRARED: {"EHUB", "EREMOTE"},
    PLATFORM_RADIO_FREQUENCY: {"EHUB", "EREMOTE"},
}
DEVICE_TYPES = set.union(*DOMAINS_AND_TYPES.values())

DEFAULT_PORT = 80
DEFAULT_TIMEOUT = 5


def get_domains(device_type: str) -> set[str]:
    """Return the domains available for a device type."""
    return {d for d, t in DOMAINS_AND_TYPES.items() if device_type in t}