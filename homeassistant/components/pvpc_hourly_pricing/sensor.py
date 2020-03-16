"""
Sensor to collect the reference daily prices of electricity ('PVPC') in Spain.

For more details about this platform, please refer to the documentation at
https://www.home-assistant.io/integrations/pvpc_hourly_pricing/
"""
from datetime import timedelta
import logging
from random import randint
from typing import Optional

from aiopvpc import PVPCData

from homeassistant import config_entries
from homeassistant.components.sensor import ENTITY_ID_FORMAT, PLATFORM_SCHEMA
from homeassistant.const import CONF_NAME, CONF_TIMEOUT
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.entity import async_generate_entity_id
from homeassistant.helpers.event import (
    async_track_point_in_time,
    async_track_time_change,
)
from homeassistant.helpers.restore_state import RestoreEntity
import homeassistant.util.dt as dt_util

from . import SENSOR_SCHEMA
from .const import ATTR_TARIFF, DEFAULT_TIMEOUT, DOMAIN

_LOGGER = logging.getLogger(__name__)

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(SENSOR_SCHEMA.schema)

ATTR_PRICE = "price"
ICON = "mdi:currency-eur"
UNIT = "€/kWh"


async def async_setup_platform(
    hass: HomeAssistant, config, async_add_devices, discovery_info=None
):
    """
    Set up the electricity price sensor as a sensor platform.

    ```yaml
    sensor:
      - platform: pvpc_hourly_pricing
        name: pvpc_manual_sensor
        tariff: normal

      - platform: pvpc_hourly_pricing
        name: pvpc_manual_sensor_2
        tariff: discrimination
        timeout: 8
    ```
    """
    hass.async_create_task(
        hass.config_entries.flow.async_init(
            DOMAIN, data=config, context={"source": config_entries.SOURCE_IMPORT}
        )
    )
    return True


async def update_listener(hass: HomeAssistant, entry: config_entries.ConfigEntry):
    """Update selected tariff for sensor."""
    if entry.options[ATTR_TARIFF] != entry.data[ATTR_TARIFF]:
        entry.data[ATTR_TARIFF] = entry.options[ATTR_TARIFF]
        hass.async_create_task(hass.config_entries.async_reload(entry.entry_id))


async def async_setup_entry(
    hass: HomeAssistant, config_entry: config_entries.ConfigEntry, async_add_entities
):
    """Set up the electricity price sensor from config_entry."""
    if not config_entry.update_listeners:
        config_entry.add_update_listener(update_listener)

    name = config_entry.data[CONF_NAME]
    entity_id = async_generate_entity_id(ENTITY_ID_FORMAT, name, hass=hass)

    pvpc_data_handler = PVPCData(
        tariff=config_entry.data[ATTR_TARIFF],
        local_timezone=hass.config.time_zone,
        websession=async_get_clientsession(hass),
        logger=_LOGGER,
        timeout=config_entry.data.get(CONF_TIMEOUT, DEFAULT_TIMEOUT),
    )
    async_add_entities([ElecPriceSensor(name, entity_id, pvpc_data_handler)], True)


class ElecPriceSensor(RestoreEntity):
    """Class to hold the prices of electricity as a sensor."""

    unit_of_measurement = UNIT
    icon = ICON
    should_poll = False

    def __init__(self, name, entity_id, pvpc_data_handler):
        """Initialize the sensor object."""
        self._name = name
        self.entity_id = entity_id
        self._pvpc_data = pvpc_data_handler
        self._num_retries = 0

        self._init_done = False
        self._hourly_tracker = None
        self._price_tracker = None

    async def async_will_remove_from_hass(self) -> None:
        """Cancel listeners for sensor updates."""
        self._hourly_tracker()
        self._price_tracker()

    async def async_added_to_hass(self):
        """Handle entity which will be added."""
        await super().async_added_to_hass()
        state = await self.async_get_last_state()
        if state:
            self._pvpc_data.state = state.state

        # Update 'state' value in hour changes
        self._hourly_tracker = async_track_time_change(
            self.hass, self.async_update, second=[0], minute=[0]
        )
        # Update prices at random time, 2 times/hour (don't want to upset API)
        random_minute = randint(1, 29)
        mins_update = [random_minute, random_minute + 30]
        self._price_tracker = async_track_time_change(
            self.hass, self.async_update_prices, second=[0], minute=mins_update,
        )
        _LOGGER.debug(
            "Setup of price sensor %s (%s) with tariff '%s', "
            "updating prices each hour at %s min",
            self.name,
            self.entity_id,
            self._pvpc_data.tariff,
            mins_update,
        )
        await self.async_update_prices(dt_util.utcnow())
        self._init_done = True
        await self.async_update_ha_state(True)

    @property
    def unique_id(self) -> Optional[str]:
        """Return a unique ID."""
        return "_".join([DOMAIN, "sensor", self.entity_id])

    @property
    def name(self):
        """Return the name of the sensor."""
        return self._name

    @property
    def state(self):
        """Return the state of the sensor."""
        return self._pvpc_data.state

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return self._pvpc_data.state_available

    @property
    def device_state_attributes(self):
        """Return the state attributes."""
        return self._pvpc_data.attributes

    async def async_update(self, *_args):
        """Update the sensor state."""
        if not self._init_done:
            # abort until added_to_hass is finished
            return

        now = dt_util.utcnow()
        if self._pvpc_data.process_state_and_attributes(now):
            await self.async_update_ha_state()
        else:
            # If no prices present, download and schedule a future state update
            self._pvpc_data.state_available = False
            self.async_schedule_update_ha_state()

            if self._pvpc_data.source_available:
                _LOGGER.debug(
                    "[%s]: Downloading prices as there are no valid ones",
                    self.entity_id,
                )
                async_track_point_in_time(
                    self.hass,
                    self.async_update,
                    now + timedelta(seconds=self._pvpc_data.timeout),
                )
            await self.async_update_prices(now)

    async def async_update_prices(self, now):
        """Update electricity prices from the ESIOS API."""
        prices = await self._pvpc_data.async_update_prices(now)
        if not prices and self._pvpc_data.source_available:
            self._num_retries += 1
            if self._num_retries > 2:
                _LOGGER.warning(
                    "Repeated bad data update, mark component as unavailable source"
                )
                self._pvpc_data.source_available = False
                return

            retry_delay = 3 * self._pvpc_data.timeout
            _LOGGER.debug(
                "Bad update[retry:%d], will try again in %d s",
                self._num_retries,
                retry_delay,
            )
            async_track_point_in_time(
                self.hass,
                self.async_update_prices,
                dt_util.now() + timedelta(seconds=retry_delay),
            )
            return

        if not prices:
            _LOGGER.debug(
                "Data source unavailable since %s",
                self.hass.states.get(self.entity_id).last_changed,
            )
            return

        self._num_retries = 0
        if not self._pvpc_data.source_available:
            self._pvpc_data.source_available = True
            _LOGGER.warning(
                "Component has recovered data access. Was unavailable since %s",
                self.hass.states.get(self.entity_id).last_changed,
            )
            self.async_schedule_update_ha_state(True)
