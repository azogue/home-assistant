"""Hue sensor entities."""
from datetime import timedelta
import logging

from aiohue.sensors import (
    TYPE_ZGP_SWITCH,
    TYPE_ZLL_SWITCH,
    ZGP_SWITCH_BUTTON_1,
    ZGP_SWITCH_BUTTON_2,
    ZGP_SWITCH_BUTTON_3,
    ZGP_SWITCH_BUTTON_4,
    ZLL_SWITCH_BUTTON_1_HOLD,
    ZLL_SWITCH_BUTTON_1_INITIAL_PRESS,
    ZLL_SWITCH_BUTTON_1_LONG_RELEASED,
    ZLL_SWITCH_BUTTON_1_SHORT_RELEASED,
    ZLL_SWITCH_BUTTON_2_HOLD,
    ZLL_SWITCH_BUTTON_2_INITIAL_PRESS,
    ZLL_SWITCH_BUTTON_2_LONG_RELEASED,
    ZLL_SWITCH_BUTTON_2_SHORT_RELEASED,
    ZLL_SWITCH_BUTTON_3_HOLD,
    ZLL_SWITCH_BUTTON_3_INITIAL_PRESS,
    ZLL_SWITCH_BUTTON_3_LONG_RELEASED,
    ZLL_SWITCH_BUTTON_3_SHORT_RELEASED,
    ZLL_SWITCH_BUTTON_4_HOLD,
    ZLL_SWITCH_BUTTON_4_INITIAL_PRESS,
    ZLL_SWITCH_BUTTON_4_LONG_RELEASED,
    ZLL_SWITCH_BUTTON_4_SHORT_RELEASED,
)

from homeassistant.components.remote import RemoteDevice
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import callback

from .const import DOMAIN as HUE_DOMAIN
from .sensor_base import SENSOR_CONFIG_MAP, GenericHueSensor

_LOGGER = logging.getLogger(__name__)

# Add ZLLRelativeRotary class and definitions to aiohue (TODO)
TYPE_ZLL_ROTARY = "ZLLRelativeRotary"

_IMPLEMENTED_REMOTE_TYPES = (TYPE_ZGP_SWITCH, TYPE_ZLL_SWITCH, TYPE_ZLL_ROTARY)

# Scan interval for remotes and binary sensors is set to < 1s
# just to ~ensure that an update is called for each HA tick,
# as using an exact 1s misses some of the ticks
DEFAULT_SCAN_INTERVAL = timedelta(seconds=0.5)

REMOTE_ICONS = {
    "RWL": "mdi:remote",
    "ROM": "mdi:remote",
    "ZGP": "mdi:remote",
    "FOH": "mdi:light-switch",
    "Z3-": "mdi:light-switch",
}
REMOTE_NAME_FORMAT = "{}"  # just the given one in Hue app

# state mapping for remote presses
FOH_BUTTONS = {
    16: "left_upper_press",
    20: "left_upper_release",
    17: "left_lower_press",
    21: "left_lower_release",
    18: "right_lower_press",
    22: "right_lower_release",
    19: "right_upper_press",
    23: "right_upper_release",
    100: "double_upper_press",
    101: "double_upper_release",
    98: "double_lower_press",
    99: "double_lower_release",
}
RWL_BUTTONS = {
    ZLL_SWITCH_BUTTON_1_INITIAL_PRESS: "1_click",
    ZLL_SWITCH_BUTTON_2_INITIAL_PRESS: "2_click",
    ZLL_SWITCH_BUTTON_3_INITIAL_PRESS: "3_click",
    ZLL_SWITCH_BUTTON_4_INITIAL_PRESS: "4_click",
    ZLL_SWITCH_BUTTON_1_HOLD: "1_hold",
    ZLL_SWITCH_BUTTON_2_HOLD: "2_hold",
    ZLL_SWITCH_BUTTON_3_HOLD: "3_hold",
    ZLL_SWITCH_BUTTON_4_HOLD: "4_hold",
    ZLL_SWITCH_BUTTON_1_SHORT_RELEASED: "1_click_up",
    ZLL_SWITCH_BUTTON_2_SHORT_RELEASED: "2_click_up",
    ZLL_SWITCH_BUTTON_3_SHORT_RELEASED: "3_click_up",
    ZLL_SWITCH_BUTTON_4_SHORT_RELEASED: "4_click_up",
    ZLL_SWITCH_BUTTON_1_LONG_RELEASED: "1_hold_up",
    ZLL_SWITCH_BUTTON_2_LONG_RELEASED: "2_hold_up",
    ZLL_SWITCH_BUTTON_3_LONG_RELEASED: "3_hold_up",
    ZLL_SWITCH_BUTTON_4_LONG_RELEASED: "4_hold_up",
}
TAP_BUTTONS = {
    ZGP_SWITCH_BUTTON_1: "1_click",
    ZGP_SWITCH_BUTTON_2: "2_click",
    ZGP_SWITCH_BUTTON_3: "3_click",
    ZGP_SWITCH_BUTTON_4: "4_click",
}
Z3_BUTTON = {
    1000: "initial_press",
    1001: "repeat",
    1002: "short_release",
    1003: "long_release",
}
Z3_DIAL = {1: "begin", 2: "end"}


async def async_setup_entry(hass, config_entry: ConfigEntry, async_add_entities):
    """Defer sensor setup to the shared sensor module."""
    manager = hass.data[HUE_DOMAIN][config_entry.entry_id].sensor_manager

    @callback
    def _async_add_entities(new_entities):
        """Add remote entitites to hue integration."""
        async_add_entities(new_entities)
        # Replace the default scan_interval in coordinator to 1Hz.
        if manager.coordinator.update_interval > timedelta(seconds=1):
            manager.coordinator.update_interval = DEFAULT_SCAN_INTERVAL
            _LOGGER.warning(
                "Added %d remotes, bridge scan frequency is now of 1Hz",
                len(new_entities),
            )

    await manager.async_register_component("remote", _async_add_entities)


class HueGenericRemote(GenericHueSensor, RemoteDevice):
    """Parent class to hold common Hue Remote entity info."""

    @property
    def icon(self):
        """Icon to use in the frontend, if any."""
        return REMOTE_ICONS.get(self.sensor.modelid[0:3])

    @property
    def force_update(self):
        """Force update."""
        return True

    def turn_on(self, **kwargs):
        """Do nothing."""

    def turn_off(self, **kwargs):
        """Do nothing."""

    @property
    def device_state_attributes(self):
        """Return the device state attributes."""
        attributes = {
            "model": self.sensor.type,
            "last_button_event": self.state or "No data",
            "last_updated": self.sensor.lastupdated.split("T"),
        }
        if hasattr(self.sensor, "battery"):
            attributes.update(
                {
                    "on": self.sensor.on,
                    "reachable": self.sensor.reachable,
                    "battery_level": self.sensor.battery,
                }
            )
        return attributes


class HueRemoteZLLSwitch(HueGenericRemote):
    """
    Class to hold ZLLSwitch remote entity info.

    Models:
    * RWL021, Hue Dimmer Switch
    * ROM001, Hue Smart button
    * Z3-1BRL, Lutron Aurora
    """

    @property
    def state(self):
        """Return the last button press of the remote."""
        if self.sensor.modelid.startswith("RWL"):
            return RWL_BUTTONS.get(self.sensor.state["buttonevent"])
        return Z3_BUTTON.get(self.sensor.state["buttonevent"])


class HueRemoteZGPSwitch(HueGenericRemote):
    """
    Class to hold ZGPSwitch remote entity info.

    Models:
    * ZGPSWITCH, Hue tap switch
    * FOHSWITCH, Friends of Hue Switch
    """

    @property
    def state(self):
        """Return the last button press of the remote."""
        if self.sensor.modelid.startswith("FOH"):
            return FOH_BUTTONS.get(self.sensor.state["buttonevent"])
        return TAP_BUTTONS.get(self.sensor.state["buttonevent"])


class HueRemoteZLLRelativeRotary(HueGenericRemote):
    """
    Class to hold ZLLRelativeRotary remote entity info.

    Models:
    * Z3-1BRL, Lutron Aurora Rotary
    """

    @property
    def state(self):
        """Return the last button press of the remote."""
        return Z3_DIAL.get(self.sensor.state["rotaryevent"])

    @property
    def device_state_attributes(self):
        """Return the device state attributes."""
        return {
            "model": self.sensor.type,
            "dial_state": self.state or "No data",
            "dial_position": self.sensor.state["expectedrotation"],
            "last_button_event": self.state or "No data",
            "last_updated": self.sensor.state["lastupdated"].split("T"),
            "name": self.sensor.name,
            "on": self.sensor.raw["config"]["on"],
            "reachable": self.sensor.raw["config"]["reachable"],
            "battery_level": self.sensor.raw["config"].get("battery"),
            "software_update": self.sensor.raw["swupdate"]["state"],
        }


SENSOR_CONFIG_MAP.update(
    {
        TYPE_ZLL_SWITCH: {
            "platform": "remote",
            "name_format": REMOTE_NAME_FORMAT,
            "class": HueRemoteZLLSwitch,
        },
        TYPE_ZGP_SWITCH: {
            "platform": "remote",
            "name_format": REMOTE_NAME_FORMAT,
            "class": HueRemoteZGPSwitch,
        },
        TYPE_ZLL_ROTARY: {
            "platform": "remote",
            "name_format": REMOTE_NAME_FORMAT,
            "class": HueRemoteZLLRelativeRotary,
        },
    }
)
