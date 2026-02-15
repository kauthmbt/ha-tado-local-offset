"""Binary sensor platform for Tado Local Offset."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo, EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_ROOM_NAME, DOMAIN, MANUFACTURER, MODEL
from .coordinator import TadoLocalOffsetCoordinator, TadoLocalOffsetData


@dataclass(frozen=True, kw_only=True)
class TadoLocalOffsetBinarySensorDescription(BinarySensorEntityDescription):
    """Describes Tado Local Offset binary sensor entity."""

    value_fn: Callable[[TadoLocalOffsetData], bool]


BINARY_SENSORS: tuple[TadoLocalOffsetBinarySensorDescription, ...] = (
    TadoLocalOffsetBinarySensorDescription(
        key="window_open",
        name="Window Open",
        device_class=BinarySensorDeviceClass.WINDOW,
        icon="mdi:window-open-variant",
        value_fn=lambda data: data.window_open,
    ),
    TadoLocalOffsetBinarySensorDescription(
        key="compensation_active",
        name="Compensation Active",
        icon="mdi:thermometer-auto",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda data: data.compensation_enabled and not (data.window_open and not data.window_override),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Tado Local Offset binary sensors from config entry."""
    coordinator: TadoLocalOffsetCoordinator = hass.data[DOMAIN][entry.entry_id]

    async_add_entities(
        TadoLocalOffsetBinarySensor(coordinator, entry, description)
        for description in BINARY_SENSORS
    )


class TadoLocalOffsetBinarySensor(CoordinatorEntity[TadoLocalOffsetCoordinator], BinarySensorEntity):
    """Binary sensor entity for Tado Local Offset."""

    entity_description: TadoLocalOffsetBinarySensorDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: TadoLocalOffsetCoordinator,
        entry: ConfigEntry,
        description: TadoLocalOffsetBinarySensorDescription,
    ) -> None:
        """Initialize the binary sensor."""
        super().__init__(coordinator)

        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._room_name = entry.data[CONF_ROOM_NAME]

        # Set up device info
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=f"{self._room_name} Virtual Thermostat",
            manufacturer=MANUFACTURER,
            model=MODEL,
            sw_version="0.1.0",
        )

    @property
    def is_on(self) -> bool:
        """Return true if the binary sensor is on."""
        return self.entity_description.value_fn(self.coordinator.data)
