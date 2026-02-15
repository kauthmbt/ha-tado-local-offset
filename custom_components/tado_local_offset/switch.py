"""Switch platform for Tado Local Offset."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo, EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_ROOM_NAME, DOMAIN, MANUFACTURER, MODEL
from .coordinator import TadoLocalOffsetCoordinator


@dataclass(frozen=True, kw_only=True)
class TadoLocalOffsetSwitchDescription(SwitchEntityDescription):
    """Describes Tado Local Offset switch entity."""

    set_fn: Callable[[TadoLocalOffsetCoordinator, bool], None]
    get_fn: Callable[[TadoLocalOffsetCoordinator], bool]


SWITCHES: tuple[TadoLocalOffsetSwitchDescription, ...] = (
    TadoLocalOffsetSwitchDescription(
        key="battery_saver",
        name="Battery Saver",
        icon="mdi:battery",
        entity_category=EntityCategory.CONFIG,
        set_fn=lambda coord, value: coord.set_battery_saver(value),
        get_fn=lambda coord: coord.data.battery_saver_enabled,
    ),
    TadoLocalOffsetSwitchDescription(
        key="window_override",
        name="Window Override",
        icon="mdi:window-open-variant",
        entity_category=EntityCategory.CONFIG,
        set_fn=lambda coord, value: coord.set_window_override(value),
        get_fn=lambda coord: coord.data.window_override,
    ),
    TadoLocalOffsetSwitchDescription(
        key="compensation_enabled",
        name="Compensation Enabled",
        icon="mdi:thermometer-auto",
        entity_category=EntityCategory.CONFIG,
        set_fn=lambda coord, value: coord.set_compensation_enabled(value),
        get_fn=lambda coord: coord.data.compensation_enabled,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Tado Local Offset switches from config entry."""
    coordinator: TadoLocalOffsetCoordinator = hass.data[DOMAIN][entry.entry_id]

    async_add_entities(
        TadoLocalOffsetSwitch(coordinator, entry, description)
        for description in SWITCHES
    )


class TadoLocalOffsetSwitch(CoordinatorEntity[TadoLocalOffsetCoordinator], SwitchEntity):
    """Switch entity for Tado Local Offset."""

    entity_description: TadoLocalOffsetSwitchDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: TadoLocalOffsetCoordinator,
        entry: ConfigEntry,
        description: TadoLocalOffsetSwitchDescription,
    ) -> None:
        """Initialize the switch."""
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
        """Return true if the switch is on."""
        return self.entity_description.get_fn(self.coordinator)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the switch on."""
        self.entity_description.set_fn(self.coordinator, True)
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the switch off."""
        self.entity_description.set_fn(self.coordinator, False)
        await self.coordinator.async_request_refresh()
