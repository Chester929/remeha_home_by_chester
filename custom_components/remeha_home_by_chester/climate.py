"""Platform for Remeha Home climate integration."""

from __future__ import annotations
from typing import Any
import logging

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_TEMPERATURE, PRECISION_HALVES, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import RemehaHomeAPI
from .const import DOMAIN
from .coordinator import RemehaHomeUpdateCoordinator
from .utils import debounce_async

_LOGGER = logging.getLogger(__name__)

REMEHA_MODE_TO_HVAC_MODE = {
    "Scheduling": HVACMode.AUTO,
    "TemporaryOverride": HVACMode.AUTO,
    "Manual": HVACMode.HEAT,
    "FrostProtection": HVACMode.OFF,
}

HVAC_MODE_TO_REMEHA_MODE = {
    HVACMode.AUTO: "Scheduling",
    HVACMode.HEAT: "Manual",
    HVACMode.OFF: "FrostProtection",
}

REMEHA_STATUS_TO_HVAC_ACTION = {
    "ProducingHeat": HVACAction.HEATING,
    "RequestingHeat": HVACAction.HEATING,
    "Idle": HVACAction.IDLE,
}

PRESET_INDEX_TO_PRESET_MODE = {
    1: "clock_program_1",
    2: "clock_program_2",
    3: "clock_program_3",
}

PRESET_MODE_TO_PRESET_INDEX = {
    "clock_program_1": 1,
    "clock_program_2": 2,
    "clock_program_3": 3,
}

# Hot Watter zone
REMEHA_HW_MODE_TO_HVAC_MODE = {
    "ContinuousComfort": HVACMode.HEAT,
    "Scheduling": HVACMode.AUTO,
    "Off": HVACMode.OFF,
}

HVAC_MODE_TO_REMEHA_HW_MODE = {
    HVACMode.AUTO: "Scheduling",
    HVACMode.HEAT: "ContinuousComfort",
    HVACMode.OFF: "Off",
}

REMEHA_HW_STATUS_TO_HVAC_ACTION = {
    "ProducingHeat": HVACAction.HEATING,
    "RequestingHeat": HVACAction.HEATING,
    "Idle": HVACAction.IDLE,
}

PRESET_INDEX_TO_HW_PRESET_MODE = {
    1: "Scheduling program",
}

HW_PRESET_MODE_TO_PRESET_INDEX = {
    "Scheduling program": 1,
}

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Remeha Home climate and hot water entity from a config entry."""
    api = hass.data[DOMAIN][entry.entry_id]["api"]
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]

    entities = []
    for appliance in coordinator.data["appliances"]:
        for climate_zone in appliance["climateZones"]:
            climate_zone_id = climate_zone["climateZoneId"]
            entities.append(RemehaHomeClimateEntity(api, coordinator, climate_zone_id))
        for hot_water_zone in appliance["hotWaterZones"]:
            hot_water_zone_id = hot_water_zone["hotWaterZoneId"]
            entities.append(RemehaHomeHotWaterEntity(api, coordinator, hot_water_zone_id))

    async_add_entities(entities)

class RemehaHomeClimateEntity(CoordinatorEntity, ClimateEntity):
    """Climate entity representing a Remeha Home climate zone."""

    _enable_turn_on_off_backwards_compatibility = False
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.PRESET_MODE
        | ClimateEntityFeature.TURN_OFF
        | ClimateEntityFeature.TURN_ON
    )
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_precision = PRECISION_HALVES
    _attr_has_entity_name = True
    _attr_name = None
    _attr_translation_key = "remeha_home_by_chester"

    def __init__(
        self,
        api: RemehaHomeAPI,
        coordinator: RemehaHomeUpdateCoordinator,
        climate_zone_id: str,
    ) -> None:
        """Create a Remeha Home climate entity."""
        super().__init__(coordinator)
        self.api = api
        self.coordinator = coordinator
        self.climate_zone_id = climate_zone_id
        self._debounce_tasks = {}

        self._attr_unique_id = "_".join([DOMAIN, self.climate_zone_id])

    @property
    def _data(self) -> dict:
        """Return the climate zone information from the coordinator."""
        return self.coordinator.get_by_id(self.climate_zone_id)

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info for this device."""
        return self.coordinator.get_device_info(self.climate_zone_id)

    @property
    def current_temperature(self) -> float | None:
        """Return the current temperature."""
        return self._data["roomTemperature"]

    @property
    def target_temperature(self) -> float | None:
        """Return the target temperature."""
        if self.hvac_mode == HVACMode.OFF:
            return None
        return self._data["setPoint"]

    @property
    def target_temperature_step(self) -> float | None:
        """Return the supported step of target temperature."""
        return 0.5

    @property
    def min_temp(self) -> float:
        """Return the minimum temperature."""
        return self._data["setPointMin"]

    @property
    def max_temp(self) -> float:
        """Return the maximum temperature."""
        return self._data["setPointMax"]

    @property
    def hvac_mode(self) -> HVACMode | str | None:
        """Return hvac target hvac state."""
        mode = self._data["zoneMode"]
        return REMEHA_MODE_TO_HVAC_MODE.get(mode)

    @property
    def hvac_modes(self) -> list[HVACMode] | list[str]:
        """Return the list of available operation modes."""
        return [HVACMode.OFF, HVACMode.HEAT, HVACMode.AUTO]

    @property
    def hvac_action(self) -> HVACAction | str | None:
        """Return hvac action."""
        if self.hvac_mode == HVACMode.OFF:
            return HVACAction.OFF

        action = self._data["activeComfortDemand"]
        return REMEHA_STATUS_TO_HVAC_ACTION.get(action)

    @property
    def preset_mode(self) -> str | None:
        """Return the preset mode."""
        if self.hvac_mode == HVACMode.OFF:
            return "anti_frost"
        if self.hvac_mode == HVACMode.HEAT:
            return "manual"
        return PRESET_INDEX_TO_PRESET_MODE[
            self._data["activeHeatingClimateTimeProgramNumber"]
        ]

    @property
    def preset_modes(self) -> list[str]:
        """Return the list of available presets."""
        return list(PRESET_INDEX_TO_PRESET_MODE.values())

    @debounce_async(5)
    async def set_temperature(self, temperature: float):
        _LOGGER.debug("API: Setting temperature to %f", temperature)
        if self.hvac_mode == HVACMode.AUTO:
            await self.api.async_set_temporary_override(self.climate_zone_id, temperature)
        elif self.hvac_mode == HVACMode.HEAT:
            await self.api.async_set_manual(self.climate_zone_id, temperature)

    @debounce_async(5)
    async def set_hvac_mode(self, hvac_mode: HVACMode):
        _LOGGER.debug("API: Setting mode to %s", HVAC_MODE_TO_REMEHA_MODE.get(hvac_mode))
        if hvac_mode == HVACMode.AUTO:
            await self.api.async_set_schedule(self.climate_zone_id, self._data["activeHeatingClimateTimeProgramNumber"])
        elif hvac_mode == HVACMode.HEAT:
            await self.api.async_set_manual(self.climate_zone_id, self._data["setPoint"])
        elif hvac_mode == HVACMode.OFF:
            await self.api.async_set_off(self.climate_zone_id)

    @debounce_async(5)
    async def activate_heating_time_program(self, target_preset: int, previous_hvac_mode: HVACMode):
        _LOGGER.debug("API: Setting heating time program to %i", target_preset)
        await self.api.async_activate_heating_time_program(self.climate_zone_id, target_preset)
        if previous_hvac_mode != HVACMode.AUTO():
            await self.api.async_set_schedule(self.climate_zone_id, target_preset)

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set new target temperature."""
        if (temperature := kwargs.get(ATTR_TEMPERATURE)) is not None:
            _LOGGER.debug("Setting temperature to %f", temperature)
            if self.hvac_mode == HVACMode.OFF:
                return

            await self.set_temperature(temperature)

            self.coordinator.trigger_update_block(60)
            await self.coordinator.async_request_refresh()

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set new operation mode."""
        _LOGGER.debug("Setting operation mode to %s", HVAC_MODE_TO_REMEHA_MODE.get(hvac_mode))

        if hvac_mode not in self.hvac_modes:
            raise NotImplementedError()

        # Temporarily override the coordinator state until the next poll
        self._data["zoneMode"] = HVAC_MODE_TO_REMEHA_MODE.get(hvac_mode)
        self.async_write_ha_state()

        await self.set_hvac_mode(hvac_mode)

        self.coordinator.trigger_update_block(60)
        await self.coordinator.async_request_refresh()

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Set new preset mode."""
        _LOGGER.debug("Setting preset mode to %s", preset_mode)

        if preset_mode not in PRESET_MODE_TO_PRESET_INDEX:
            _LOGGER.error("Trying to set unknown preset mode %s", preset_mode)
            return

        target_preset = PRESET_MODE_TO_PRESET_INDEX[preset_mode]
        previous_hvac_mode = self.hvac_mode

        self._data["zoneMode"] = HVAC_MODE_TO_REMEHA_MODE.get(HVACMode.AUTO)
        self._data["activeHeatingClimateTimeProgramNumber"] = target_preset
        self.async_write_ha_state()

        # Switch the selected heating time program
        await self.activate_heating_time_program(target_preset, previous_hvac_mode)

        self.coordinator.trigger_update_block(60)
        await self.coordinator.async_request_refresh()

class RemehaHomeHotWaterEntity(CoordinatorEntity, ClimateEntity):
    """Climate entity representing a Remeha Home hot water zone."""

    _enable_turn_on_off_backwards_compatibility = False
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.PRESET_MODE
        | ClimateEntityFeature.TURN_OFF
        | ClimateEntityFeature.TURN_ON
    )
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_precision = PRECISION_HALVES
    _attr_has_entity_name = True
    _attr_name = None
    _attr_translation_key = "remeha_home_by_chester"

    def __init__(
        self,
        api: RemehaHomeAPI,
        coordinator: RemehaHomeUpdateCoordinator,
        hot_water_zone_id: str,
    ) -> None:
        """Create a Remeha Home climate entity."""
        super().__init__(coordinator)
        self.api = api
        self.coordinator = coordinator
        self.hot_water_zone_id = hot_water_zone_id
        self._debounce_tasks = {}

        self._attr_unique_id = "_".join([DOMAIN, self.hot_water_zone_id])

    @property
    def _data(self) -> dict:
        """Return the climate zone information from the coordinator."""

        data = self.coordinator.get_by_id(self.hot_water_zone_id)
        return data

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info for this device."""
        return self.coordinator.get_device_info(self.hot_water_zone_id)

    @property
    def current_temperature(self) -> float | None:
        """Return the current temperature."""
        return self._data["dhwTemperature"]

    @property
    def target_temperature(self) -> float | None:
        """Return the target temperature."""
        if self.hvac_mode == HVACMode.AUTO or self.hvac_mode == HVACMode.OFF:
            return None
        return self._data["targetSetpoint"]

    @property
    def target_temperature_step(self) -> float | None:
        """Return the supported step of target temperature."""
        if self.hvac_mode == HVACMode.AUTO:
            return None
        return 1.0

    @property
    def min_temp(self) -> float:
        """Return the minimum temperature."""
        return self._data.get('setPointRanges', {}).get('reducedSetpointMin', 20.0)

    @property
    def max_temp(self) -> float:
        """Return the maximum temperature."""
        return self._data["setPointMax"]

    @property
    def hvac_mode(self) -> HVACMode | str | None:
        """Return hvac target hvac state."""
        mode = self._data["dhwZoneMode"]
        return REMEHA_HW_MODE_TO_HVAC_MODE.get(mode)

    @property
    def hvac_modes(self) -> list[HVACMode] | list[str]:
        """Return the list of available operation modes."""
        return [HVACMode.OFF, HVACMode.HEAT, HVACMode.AUTO]

    @property
    def hvac_action(self) -> HVACAction | str | None:
        """Return hvac action."""
        if self.hvac_mode == HVACMode.OFF:
            return HVACAction.OFF

        action = self._data["dhwStatus"]
        return REMEHA_HW_STATUS_TO_HVAC_ACTION.get(action)

    @property
    def preset_mode(self) -> str | None:
        """Return the preset mode."""
        if self.hvac_mode == HVACMode.OFF:
            return "anti_frost"
        if self.hvac_mode == HVACMode.HEAT:
            return "manual"
        return PRESET_INDEX_TO_HW_PRESET_MODE[
            self._data["activeDwhTimeProgramNumber"]
        ]

    @property
    def preset_modes(self) -> list[str]:
        """Return the list of available presets."""
        return list(PRESET_INDEX_TO_HW_PRESET_MODE.values())

    @debounce_async(5)
    async def set_continuous_comfort_with_temperature(self, temperature: float):
        _LOGGER.debug("API: Setting temperature to %f", temperature)
        await self.api.async_hw_set_comfort_setpoint(self.hot_water_zone_id, temperature)
        await self.api.async_hw_set_continuous_comfort(self.hot_water_zone_id)

    @debounce_async(5)
    async def set_hvac_mode(self, hvac_mode: HVACMode):
        _LOGGER.debug("API: Setting mode to %s", hvac_mode)
        if hvac_mode == HVACMode.AUTO:
            await self.api.async_hw_set_schedule(self.hot_water_zone_id)
        elif hvac_mode == HVACMode.HEAT:
            await self.api.async_hw_set_continuous_comfort(self.hot_water_zone_id)
        elif hvac_mode == HVACMode.OFF:
            await self.api.async_hw_set_off(self.hot_water_zone_id)

    @debounce_async(5)
    async def set_schedule(self):
        _LOGGER.debug("API: Setting schedule")
        await self.api.async_hw_set_schedule(self.hot_water_zone_id)

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set new target temperature."""
        if (temperature := kwargs.get(ATTR_TEMPERATURE)) is not None:
            _LOGGER.debug("Set temperature to %f", temperature) # print in float
            temperature = int(temperature) # dhw has only int numbers for temperature

            if self.hvac_mode == HVACMode.HEAT:
                await self.set_continuous_comfort_with_temperature(temperature)
                self.coordinator.trigger_update_block(60)
                self._data['targetSetpoint'] = float(temperature)
                self._data['dhwZoneMode'] = HVAC_MODE_TO_REMEHA_HW_MODE.get(HVACMode.HEAT)
                self.async_write_ha_state()
            else:
                return

            await self.coordinator.async_request_refresh()

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set new operation mode."""
        _LOGGER.debug("Setting operation mode to %s", HVAC_MODE_TO_REMEHA_HW_MODE.get(hvac_mode))

        if hvac_mode not in self.hvac_modes:
            raise NotImplementedError()

        # Temporarily override the coordinator state until the next poll
        self._data["dhwZoneMode"] = HVAC_MODE_TO_REMEHA_HW_MODE.get(hvac_mode)

        if hvac_mode == HVACMode.HEAT:
            self._data['targetSetpoint'] = self._data['comfortSetPoint']
        elif hvac_mode == HVACMode.OFF:
            self._data['targetSetpoint'] = 10.0

        await self.set_hvac_mode(hvac_mode)

        self.async_write_ha_state()
        self.coordinator.trigger_update_block(60)
        await self.coordinator.async_request_refresh()

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Set new preset mode."""
        _LOGGER.debug("Setting preset mode to %s", preset_mode)

        if preset_mode not in HW_PRESET_MODE_TO_PRESET_INDEX:
            _LOGGER.error("Trying to set unknown preset mode %s", preset_mode)
            return

        target_preset = HW_PRESET_MODE_TO_PRESET_INDEX[preset_mode]
        previous_hvac_mode = self.hvac_mode

        # Set mode to schedule
        if previous_hvac_mode != HVACMode.AUTO:
            self._data["dhwZoneMode"] = HVAC_MODE_TO_REMEHA_HW_MODE.get(HVACMode.AUTO)
            self._data["activeDwhTimeProgramNumber"] = target_preset
            self.async_write_ha_state()
            await self.set_schedule()
            self.coordinator.trigger_update_block(60)

        await self.coordinator.async_request_refresh()
