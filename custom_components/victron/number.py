"""Support for victron energy slider number entities."""

from __future__ import annotations

from dataclasses import dataclass
import logging

from homeassistant import config_entries
from homeassistant.components.number import (
    NumberEntity,
    NumberEntityDescription,
    NumberMode,
    DOMAIN as NUMBER_DOMAIN,
)

from homeassistant.const import (
    PERCENTAGE,
    UnitOfElectricPotential,
    UnitOfPower,
    UnitOfElectricCurrent,
)

from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers import entity

from .coordinator import victronEnergyDeviceUpdateCoordinator
from .base import VictronWriteBaseEntityDescription
from .const import (
    DOMAIN,
    register_info_dict,
    SliderWriteType,
    CONF_ADVANCED_OPTIONS,
    UINT16_MAX,
    CONF_DC_SYSTEM_VOLTAGE,
    CONF_DC_CURRENT_LIMIT,
    CONF_NUMBER_OF_PHASES,
    CONF_USE_SLIDERS,
    CONF_AC_SYSTEM_VOLTAGE,
    CONF_AC_CURRENT_LIMIT,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: config_entries.ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up victron switch devices."""
    victron_coordinator: victronEnergyDeviceUpdateCoordinator = hass.data[DOMAIN][
        config_entry.entry_id
    ]
    _LOGGER.debug("attempting to setup number entities")
    descriptions = []
    _LOGGER.debug(config_entry)
    # TODO cleanup
    if config_entry.options[CONF_ADVANCED_OPTIONS]:
        register_set = victron_coordinator.processed_data()["register_set"]
        for slave, registerLedger in register_set.items():
            for name in registerLedger:
                for register_name, registerInfo in register_info_dict[name].items():
                    _LOGGER.debug(
                        "unit == $s register_ledger == %s registerInfo",
                        {str(slave), str(registerLedger)},
                    )

                    if isinstance(registerInfo.entityType, SliderWriteType):
                        description = VictronEntityDescription(
                            key=register_name,
                            name=register_name.replace("_", " "),
                            slave=slave,
                            native_unit_of_measurement=registerInfo.unit,
                            mode=NumberMode.SLIDER
                            if config_entry.options[CONF_USE_SLIDERS]
                            else NumberMode.BOX,
                            native_min_value=determine_min_value(
                                registerInfo.unit,
                                config_entry.options,
                                registerInfo.entityType.powerType,
                                registerInfo.entityType.negative,
                            ),
                            native_max_value=determine_max_value(
                                registerInfo.unit,
                                config_entry.options,
                                registerInfo.entityType.powerType,
                            ),
                            entity_category=EntityCategory.CONFIG,
                            address=registerInfo.register,
                            scale=registerInfo.scale,
                            native_step=registerInfo.step,
                        )
                        _LOGGER.debug("composed description == %s", {str(description)})
                        descriptions.append(description)

    entities = []
    entity = {}
    for description in descriptions:
        entity = description
        entities.append(VictronNumber(victron_coordinator, entity))
    _LOGGER.debug("adding number")
    async_add_entities(entities)
    _LOGGER.debug("adding numbering")


def determine_min_value(
    unit, config_entry: config_entries.ConfigEntry, powerType, negative: bool
) -> int:
    if unit == PERCENTAGE:
        return 0
    elif unit == UnitOfElectricPotential.VOLT:
        series_type = (
            int(config_entry[CONF_DC_SYSTEM_VOLTAGE]) / 3
        )  # statically based on lifepo4 cells
        min_value = series_type * 2.5  # statically based on lifepo4 cells
        return min_value
    elif unit == UnitOfPower.WATT:
        if negative:
            min_value = (
                (
                    int(config_entry[CONF_AC_SYSTEM_VOLTAGE])
                    * int(config_entry[CONF_NUMBER_OF_PHASES])
                    * config_entry[CONF_AC_CURRENT_LIMIT]
                )
                if powerType == "AC"
                else (
                    int(config_entry[CONF_DC_SYSTEM_VOLTAGE].dc_voltage)
                    * config_entry[CONF_DC_CURRENT_LIMIT]
                )
            )
            rounded_min = -round(min_value / 100) * 100
            _LOGGER.debug(rounded_min)
            return rounded_min
        else:
            return 0
    elif unit == UnitOfElectricCurrent.AMPERE:
        if negative:
            if powerType == "AC":
                return -config_entry[CONF_AC_CURRENT_LIMIT]
            elif powerType == "DC":
                return -config_entry[CONF_DC_CURRENT_LIMIT]
        else:
            return 0
    else:
        return 0


def determine_max_value(
    unit, config_entry: config_entries.ConfigEntry, powerType
) -> int:
    if unit == PERCENTAGE:
        return 100
    elif unit == UnitOfElectricPotential.VOLT:
        series_type = (
            int(config_entry[CONF_DC_SYSTEM_VOLTAGE]) / 3
        )  # statically based on lifepo4 cells
        max_value = series_type * 3.65  # statically based on lifepo4 cells
        return max_value
    elif unit == UnitOfPower.WATT:
        max_value = (
            (
                int(config_entry[CONF_AC_SYSTEM_VOLTAGE])
                * int(config_entry[CONF_NUMBER_OF_PHASES])
                * config_entry[CONF_AC_CURRENT_LIMIT]
            )
            if powerType == "AC"
            else (
                int(config_entry[CONF_DC_SYSTEM_VOLTAGE])
                * config_entry[CONF_DC_CURRENT_LIMIT]
            )
        )
        rounded_max = round(max_value / 100) * 100
        return rounded_max
    elif unit == UnitOfElectricCurrent.AMPERE:
        if powerType == "AC":
            return config_entry[CONF_AC_CURRENT_LIMIT]
        elif powerType == "DC":
            return config_entry[CONF_DC_CURRENT_LIMIT]
    else:
        return 0


@dataclass
class VictronNumberMixin:
    """A class that describes number entities."""

    scale: int | None = None
    mode: bool | None = None


@dataclass
class VictronNumberStep:
    native_step: float = 0


@dataclass
class VictronEntityDescription(
    NumberEntityDescription,
    VictronWriteBaseEntityDescription,
    VictronNumberMixin,
    VictronNumberStep,
):
    # Overwrite base entitydescription property to resolve automatic property
    # ordering issues when a mix of non-default and default properties are used
    key: str | None = None
    """Describes victron number entity."""


class VictronNumber(NumberEntity):
    """Victron number."""

    description: VictronEntityDescription

    def __init__(
        self,
        coordinator: victronEnergyDeviceUpdateCoordinator,
        description: VictronEntityDescription,
    ) -> None:
        """Initialize the entity."""
        self.coordinator = coordinator
        self.description = description
        self._attr_name = f"{description.name}"

        self.data_key = str(self.description.slave) + "." + str(self.description.key)

        self._attr_native_value = self.description.value_fn(
            self.coordinator.processed_data(),
            self.description.slave,
            self.description.key,
        )

        self._attr_unique_id = f"{self.description.slave}_{self.description.key}"
        if self.description.slave not in (100, 225):
            self.entity_id = f"{NUMBER_DOMAIN}.{DOMAIN}_{self.description.key}_{self.description.slave}"
        else:
            self.entity_id = f"{NUMBER_DOMAIN}.{DOMAIN}_{self.description.key}"

        self._attr_mode = self.description.mode

    async def async_set_native_value(self, value: float) -> None:
        """Update the current value."""
        # TODO convert float to int again with scale respected
        if value < 0:
            value = UINT16_MAX + value
        self.coordinator.write_register(
            unit=self.description.slave,
            address=self.description.address,
            value=self.coordinator.encode_scaling(
                value,
                self.description.native_unit_of_measurement,
                self.description.scale,
            ),
        )
        await self.coordinator.async_update_local_entry(self.data_key, int(value))

    @property
    def native_value(self) -> float:
        """Return the state of the entity."""
        value = self.description.value_fn(
            data=self.coordinator.processed_data(),
            slave=self.description.slave,
            key=self.description.key,
        )
        if value > round(
            UINT16_MAX / 2
        ):  # Half of the UINT16 is reserved for positive and half for negative values
            value = value - UINT16_MAX
        return value

    @property
    def native_step(self) -> float | None:
        if (
            not self.description.mode == NumberMode.SLIDER
        ):  # allow users to skip stepping in case of box mode
            return None
        if self.description.native_step > 0:
            return self.description.native_step
        max = self.native_max_value
        min = self.native_min_value
        gap = len(list(range(int(min), int(max), 1)))
        # TODO optimize gap step selection
        if gap >= 3000:
            return 100
        elif gap < 3000 and gap > 100:
            return 10
        else:
            return 1

    @property
    def native_min_value(self) -> float:
        return self.description.native_min_value

    @property
    def native_max_value(self) -> float:
        return self.description.native_max_value

    @property
    def available(self) -> bool:
        full_key = str(self.description.slave) + "." + self.description.key
        return self.coordinator.processed_data()["availability"][full_key]

    @property
    def device_info(self) -> entity.DeviceInfo:
        """Return the device info."""
        return entity.DeviceInfo(
            identifiers={(DOMAIN, self.unique_id.split("_")[0])},
            name=self.unique_id.split("_")[1],
            model=self.unique_id.split("_")[0],
            manufacturer="victron",
        )
