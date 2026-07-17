"""Diagnostics for the Lambda Heat Pumps integration.

The download dumps the controller's raw registers — the undecoded words, block by
block, exactly as they come off the wire. That is what makes a diagnostics
download worth having here: a value that reads wrong in Home Assistant can be
checked against the datasheet without a Modbus tool, and a register the
integration does not model yet can be read straight out of the dump.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant
from modbus_connection import ModbusError

from .const import CONF_HOST
from .coordinator import LambdaConfigEntry
from .lambda_modbus.ranges import (
    CAPACITY_LIMIT_RANGES,
    REFRIGERANT_RANGES,
    base_address,
    readable_ranges,
)

# The host is the one thing here that identifies where the user lives on their
# network; everything else describes the appliance.
TO_REDACT = {CONF_HOST}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: LambdaConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = entry.runtime_data

    return {
        "entry": {
            "data": async_redact_data(dict(entry.data), TO_REDACT),
            "options": dict(entry.options),
        },
        "detected_modules": coordinator.counts,
        "registers": await _async_read_registers(coordinator),
        # What the integration counts for itself, so a wrong cycle or energy
        # figure can be told apart from a wrong register.
        "totals": {
            index: {
                "cycles": totals.cycles,
                "electrical": totals.electrical,
                "thermal": totals.thermal,
            }
            for index, totals in coordinator.totals.items()
        },
    }


async def _async_read_registers(coordinator) -> dict[str, Any]:
    """The controller's raw holding registers, address -> value.

    Reads the blocks the model polls, plus each heat pump's refrigerant-circuit
    block — which some firmwares refuse. A refused block is skipped rather than
    failing the dump, so it covers exactly the registers this controller serves.
    """
    registers: dict[int, int] = {}
    for low, high in _blocks(coordinator):
        try:
            values = await coordinator.unit.read_holding_registers(low, high - low + 1)
        except ModbusError:
            continue  # a block this controller does not serve
        registers.update(zip(range(low, high + 1), values, strict=True))
    # JSON object keys are strings; keep them numeric-looking and sorted so the
    # dump reads like an address map.
    return {str(address): registers[address] for address in sorted(registers)}


def _blocks(coordinator) -> list[tuple[int, int]]:
    """Every readable block, plus each heat pump's firmware-dependent ones."""
    blocks = list(readable_ranges(coordinator.counts))
    for index in range(1, coordinator.counts["hp"] + 1):
        base = base_address("hp", index)
        for low, high in (*REFRIGERANT_RANGES, *CAPACITY_LIMIT_RANGES):
            blocks.append((base + low, base + high))
    return blocks
