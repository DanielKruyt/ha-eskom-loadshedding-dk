"""
Custom integration to integrate the Eskom Loadshedding Interface with Home Assistant.

For more details about this integration, please refer to
https://github.com/swartjean/ha-eskom-loadshedding
"""
import asyncio
from datetime import timedelta
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Config, HomeAssistant, ServiceCall
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .calendar import (
    LoadsheddingLocalEventCalendar,
    LoadsheddingLocalScheduleCalendar
)
from .const import (
    CONF_SCAN_PERIOD,
    CONF_API_KEY,
    DEFAULT_SCAN_PERIOD,
    DOMAIN,
    PLATFORMS,
    STARTUP_MESSAGE,
    PROVIDE_ALL_LOCAL_EVENTS_TO_SERVICE,
    PROVIDE_ALL_LOCAL_SCHEDULE_TO_SERVICE
)
from .eskom_interface import EskomInterface

_LOGGER = logging.getLogger(__name__)


async def async_setup(hass: HomeAssistant, config: Config):
    """Setting up this integration using YAML is not supported."""
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Set up this integration using UI."""
    if hass.data.get(DOMAIN) is None:
        hass.data.setdefault(DOMAIN, {})
        _LOGGER.info(STARTUP_MESSAGE)

    scan_period = timedelta(
        seconds=entry.options.get(CONF_SCAN_PERIOD, DEFAULT_SCAN_PERIOD)
    )

    # Fetch the configured API key and area ID and create the client
    api_key = entry.options.get(CONF_API_KEY, entry.data.get("api_key"))
    area_id = entry.data.get("area_id")
    session = async_get_clientsession(hass)
    client = EskomInterface(session=session, api_key=api_key, area_id=area_id)

    coordinator = EskomDataUpdateCoordinator(hass, scan_period, client)
    await coordinator.async_refresh()

    if not coordinator.last_update_success:
        raise ConfigEntryNotReady

    hass.data[DOMAIN][entry.entry_id] = coordinator

    for platform in PLATFORMS:
        if entry.options.get(platform, True):
            coordinator.platforms.append(platform)
            hass.async_add_job(
                hass.config_entries.async_forward_entry_setup(entry, platform)
            )

    if not entry.update_listeners:
        entry.add_update_listener(async_reload_entry)

    # Registration of service(s):

    def provide_all_local_events_to_service(call: ServiceCall):
        params = dict(call.data)
        _LOGGER.info(params)
        local_events_data = LoadsheddingLocalEventCalendar.static_get_events(coordinator)
        hass.services.call(domain=params["service_domain"], service=params["service_name"], service_data={"events": local_events_data})

    hass.services.async_register(DOMAIN, PROVIDE_ALL_LOCAL_EVENTS_TO_SERVICE, provide_all_local_events_to_service)

    def provide_all_local_schedule_to_service(call: ServiceCall):
        params = dict(call.data)
        _LOGGER.debug(params)
        local_schedule_data = LoadsheddingLocalScheduleCalendar.static_get_events(coordinator)
        _LOGGER.debug(local_schedule_data)
        hass.services.call(domain=params["service_domain"], service=params["service_name"], service_data={"events": local_schedule_data})

    hass.services.async_register(DOMAIN, PROVIDE_ALL_LOCAL_SCHEDULE_TO_SERVICE, provide_all_local_schedule_to_service)

    return True


class EskomDataUpdateCoordinator(DataUpdateCoordinator):
    """Class to manage fetching data from the API."""

    def __init__(self, hass, scan_period, client: EskomInterface):
        """Initialize."""
        self.client = client
        self.platforms = []

        super().__init__(hass, _LOGGER, name=DOMAIN, update_interval=scan_period)

    async def _async_update_data(self):
        """Update data via library."""
        try:
            return await self.client.async_get_data()
        except Exception as exception:
            raise UpdateFailed(exception)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Handle removal of an entry."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    unloaded = all(
        await asyncio.gather(
            *[
                hass.config_entries.async_forward_entry_unload(entry, platform)
                for platform in PLATFORMS
                if platform in coordinator.platforms
            ]
        )
    )

    if unloaded:
        hass.data[DOMAIN].pop(entry.entry_id)

    return unloaded


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Reload config entry."""
    await hass.config_entries.async_reload(entry.entry_id)
