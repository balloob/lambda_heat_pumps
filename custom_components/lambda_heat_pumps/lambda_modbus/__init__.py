"""A Lambda heat pump controller, as an object over Modbus.

This package talks to the controller and nothing else — it has no Home Assistant
import, takes a :class:`modbus_connection.ModbusUnit` rather than a host or a
connection, and is tested against the in-memory mock backend. It lives inside the
integration for now because Home Assistant can only load what it ships; it is
shaped to be lifted out into its own PyPI package unchanged, which is what Core
would require.

    from modbus_connection.tmodbus import connect_tcp
    from lambda_modbus import LambdaHeatPump

    connection = await connect_tcp("192.168.1.50", port=502)
    try:
        controller = LambdaHeatPump(connection.for_unit(1), num_hps=2)
        await controller.async_update()
        print(controller.ambient.temperature)
        print(controller.heat_pumps[0].flow_line_temperature)
    finally:
        await connection.close()
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from dataclasses import dataclass, field
import logging

from modbus_connection import BlockReadError
from modbus_connection.model import Component, Range

from .boiler import Boiler
from .buffer import Buffer
from .general import Ambient, EManager
from .heat_pump import (
    HeatPump,
    HeatPumpCapacityLimits,
    HeatPumpLowFirst,
    HeatPumpRefrigerant,
)
from .heating_circuit import HeatingCircuit
from .model import LambdaComponent
from .ranges import (
    CAPACITY_LIMIT_RANGES,
    REFRIGERANT_RANGES,
    base_address,
    readable_ranges,
)
from .solar import Solar, SolarLowFirst

if TYPE_CHECKING:
    from modbus_connection import ModbusUnit, WordOrder


@dataclass
class OptionalBlock:
    """A firmware-dependent heat pump block, one component per heat pump.

    `available` is the set of heat pumps (1-based) whose controller answered for
    the block; the rest refuse it and get no entities for it.
    """

    components: list[LambdaComponent]
    available: set[int] = field(default_factory=set)
    # Heat pumps whose controller refused the block. A refusal is the controller
    # saying it does not serve these registers — it will not start on the same
    # connection — so they are not asked again. A reconnect reloads the entry,
    # which rebuilds this and probes afresh.
    _refused: set[int] = field(default_factory=set)

    async def async_update(self) -> None:
        """Read each heat pump's block, once dropping the ones that refuse it."""
        for index, component in enumerate(self.components, 1):
            if index in self._refused:
                continue
            try:
                await component.async_update()
            except BlockReadError:
                self._refused.add(index)
                self.available.discard(index)
            else:
                self.available.add(index)


_LOGGER = logging.getLogger(__name__)

__all__ = [
    "Ambient",
    "Boiler",
    "Buffer",
    "EManager",
    "HeatPump",
    "HeatingCircuit",
    "LambdaComponent",
    "LambdaHeatPump",
    "Solar",
]


class LambdaHeatPump:
    """A Lambda controller with the modules that are installed on it.

    `word_order` is how the controller lays out its 32-bit counters across two
    registers: `"big"` (the default, high word first) or `"little"`. It varies by
    controller, which is why it is configurable rather than modelled.
    """

    def __init__(
        self,
        unit: ModbusUnit,
        *,
        num_hps: int = 1,
        num_boil: int = 1,
        num_buff: int = 0,
        num_sol: int = 0,
        num_hc: int = 1,
        word_order: WordOrder = "big",
    ) -> None:
        self._unit = unit

        heat_pump_class = HeatPump if word_order == "big" else HeatPumpLowFirst
        solar_class = Solar if word_order == "big" else SolarLowFirst

        self.ambient = Ambient(unit)
        self.e_manager = EManager(unit)
        self.heat_pumps = self._build(heat_pump_class, unit, "hp", num_hps)
        self.boilers = self._build(Boiler, unit, "boil", num_boil)
        self.buffers = self._build(Buffer, unit, "buff", num_buff)
        self.solar_modules = self._build(solar_class, unit, "sol", num_sol)
        self.heating_circuits = self._build(HeatingCircuit, unit, "hc", num_hc)

        # Which registers the controller answers depends on which modules are
        # installed, so the ranges are computed here and pushed onto every
        # component — a ComponentGroup requires its members to agree on them.
        ranges = readable_ranges(
            {
                "hp": num_hps,
                "boil": num_boil,
                "buff": num_buff,
                "sol": num_sol,
                "hc": num_hc,
            }
        )
        for component in self.components:
            component.register_ranges = ranges

        # A controller's register map is firmware-dependent: any block may be one
        # this controller refuses. A refused block only makes its own values
        # unavailable — it never fails the whole device — so components are read
        # one at a time rather than pooled all-or-nothing, and a component that
        # refuses is not asked again on this connection.
        self._refused: set[Component] = set()

        # Some heat pump blocks are firmware-dependent — a controller either
        # serves them or refuses them outright — so each is read on its own,
        # apart from the group, and a refusal only drops that block. Each
        # `OptionalBlock` holds one component per heat pump and the set of heat
        # pumps (1-based) that answered for it on the last poll.
        self.refrigerant = self._optional_block(
            HeatPumpRefrigerant, REFRIGERANT_RANGES, num_hps
        )
        self.capacity_limits = self._optional_block(
            HeatPumpCapacityLimits, CAPACITY_LIMIT_RANGES, num_hps
        )
        self.optional_blocks = (self.refrigerant, self.capacity_limits)

    def _optional_block(
        self,
        component_class: type[LambdaComponent],
        ranges: tuple[Range, ...],
        num_hps: int,
    ) -> OptionalBlock:
        """Build one firmware-dependent component per heat pump."""
        components = self._build(component_class, self._unit, "hp", num_hps)
        for index, component in enumerate(components, 1):
            base = base_address("hp", index)
            component.register_ranges = tuple(
                (base + low, base + high) for low, high in ranges
            )
        return OptionalBlock(components)

    @staticmethod
    def _build[C: LambdaComponent](
        component_class: type[C], unit: ModbusUnit, module: str, count: int
    ) -> list[C]:
        """One component per installed module, each at its own 100-register block."""
        return [
            component_class(unit, index=index, base_offset=base_address(module, index))
            for index in range(1, count + 1)
        ]

    @property
    def components(self) -> tuple[Component, ...]:
        """Every sub-system that is polled."""
        return (
            self.ambient,
            self.e_manager,
            *self.heat_pumps,
            *self.boilers,
            *self.buffers,
            *self.solar_modules,
            *self.heating_circuits,
        )

    async def async_update(self) -> None:
        """Refresh every sub-system, tolerating any block the controller refuses.

        A refused block makes only its own values unavailable. A timeout or a
        dropped link is different — it is not the controller declining a block —
        so it propagates and the whole device goes unavailable.
        """
        for component in self.components:
            if component in self._refused:
                continue
            try:
                await component.async_update()
            except BlockReadError as err:
                _LOGGER.info(
                    "The controller refused %s registers %d-%d; those values "
                    "will be unavailable until the integration reloads",
                    err.space,
                    err.address,
                    err.address + err.count - 1,
                )
                self._refused.add(component)
        for block in self.optional_blocks:
            await block.async_update()
