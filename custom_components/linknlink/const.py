"""Constants for the linknlink integration."""
from homeassistant.const import Platform

DOMAIN = "linknlink"

DOMAINS_AND_TYPES = {
    Platform.REMOTE: {"EHUB", "EREMOTE"},
    Platform.SENSOR: {"EHUB", "ETHS", "EREMOTE"},
    Platform.BINARY_SENSOR: {"EHUB", "EMOTION", "EREMOTE"},
    Platform.BUTTON: {"EREMOTE"},
}
DEVICE_TYPES = set.union(*DOMAINS_AND_TYPES.values())

DEFAULT_PORT = 80
DEFAULT_TIMEOUT = 5


def get_domains(device_type: str) -> set[Platform]:
    """Return the domains available for a device type."""
    return {d for d, t in DOMAINS_AND_TYPES.items() if device_type in t}