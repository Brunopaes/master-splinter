"""Mutable tissue state shared by the dive handlers.

The decompression model in splinter_decompression is a set of pure functions.
This module holds the part that is genuinely stateful and order dependent -
tissue pressures, the gradient factor anchor, and the clock - so that both the
profile analyser and the future live dive handler drive identical semantics.

"""

from dataclasses import dataclass, field

from master_splinter.configs.environment import SURFACE_PRESSURE
from master_splinter.configs.limits import N2_FRACTION_AIR
from master_splinter.model.splinter_decompression import (
    ambient_pressure_at_depth,
    calculate_deco_schedule,
    calculate_first_stop_depth,
    calculate_stop_ceiling,
    initialize_tissues,
    is_ascent_safe,
    is_ascent_safe_gradient_factors,
    load_gas_at_pressure,
)


@dataclass
class DiveState:
    """Tissue loading and gradient factor anchor at a point in a dive.

    Attributes:
    -----------
    tissues: list
        The 16 tissue nitrogen pressures (in Bar).
    anchor: float
        Depth the gradient factor line is anchored to (meters). Only ever
        deepens - see the note on update_anchor.
    clock: float
        Elapsed dive time (minutes).
    gf_low: float
        Gradient factor at the first stop depth.
    gf_high: float
        Gradient factor at the surface.
    gas_fraction: float
        Nitrogen fraction of the breathing gas.
    surface_pressure: float
        Ambient pressure at the surface (in Bar).

    """

    tissues: list[float] = field(default_factory=initialize_tissues)
    anchor: float = 0.0
    clock: float = 0.0
    gf_low: float = 0.30
    gf_high: float = 0.85
    gas_fraction: float = N2_FRACTION_AIR
    surface_pressure: float = SURFACE_PRESSURE

    @classmethod
    def at_surface(cls, **kwargs):
        """Builds a state in equilibrium with surface air.

        Parameters:
        -----------
        **kwargs:
            Any DiveState field except `tissues`, which is derived from
            `surface_pressure`.

        Returns:
        --------
        state: DiveState
            A state with tissues at surface equilibrium.

        """
        surface_pressure = kwargs.get("surface_pressure", SURFACE_PRESSURE)
        return cls(
            tissues=initialize_tissues(pressure_surface=surface_pressure),
            **kwargs,
        )

    def update_anchor(self):
        """Deepens the gradient factor anchor if the dive now demands it.

        Notes:
        ------
        The anchor never shallows. Letting it do so would re-anchor the
        gradient factor line on whichever stop happened to be reached first,
        and the ceiling could then deepen underneath the diver - which reads
        as a descent partway up the ascent.

        """
        self.anchor = max(
            self.anchor,
            calculate_first_stop_depth(
                self.tissues,
                gf_low=self.gf_low,
                surface_pressure=self.surface_pressure,
            ),
        )

    @property
    def ceiling(self):
        """Shallowest depth the diver may currently ascend to (meters)."""
        return calculate_stop_ceiling(
            self.tissues,
            gf_low=self.gf_low,
            gf_high=self.gf_high,
            first_stop_depth=self.anchor,
            surface_pressure=self.surface_pressure,
        )

    def step(self, depth: float, duration: float):
        """Advances the dive by spending `duration` minutes at `depth`.

        Parameters:
        -----------
        depth: float
            Depth held for this step (meters).
        duration: float
            Length of the step (minutes).

        Notes:
        ------
        The single place tissues are loaded and the clock and anchor advance.
        Both handlers go through here, so neither can diverge on the anchor
        rule.

        The anchor is refreshed *after* loading, so it reflects the state the
        diver is actually in. Refreshing beforehand leaves it a full step
        stale, which is invisible when stepping every 10 seconds and badly
        wrong when a caller takes one large step.

        """
        self.step_at_pressure(
            ambient_pressure_at_depth(depth, self.surface_pressure),
            duration,
        )

    def step_at_pressure(self, ambient_pressure: float, duration: float):
        """Advances the dive by spending `duration` at an ambient pressure.

        Parameters:
        -----------
        ambient_pressure: float
            Ambient pressure held for this step (Bar).
        duration: float
            Length of the step (minutes). Zero is a no-op; negative is
            rejected.

        Raises:
        -------
        ValueError
            If `duration` is negative.

        Notes:
        ------
        The primitive `step` is expressed in. Depth and elevation are two ways
        of naming a pressure, so a live handler can drive this from either
        without the model needing to know which the diver is doing. Use
        `atmosphere.pressure_at_elevation` for the altitude direction.

        A negative duration runs the exponential backwards, which does not
        fail - it silently drives the tissues away from the inspired pressure
        and winds the clock back. Rejected rather than clamped, unlike
        `age_tissues`: that clamps because it is handed wall-clock intervals
        and a clock can legitimately go backwards, whereas nothing downstream
        of a validated profile should ever produce a negative step. A caller
        deriving `duration` from timestamps owns that problem and should use
        a monotonic clock.

        """
        if duration < 0.0:
            raise ValueError(f"duration must not be negative, got {duration}")

        self.tissues = load_gas_at_pressure(
            self.tissues,
            ambient_pressure,
            duration,
            gas_fraction=self.gas_fraction,
        )
        self.clock += duration
        self.update_anchor()

    def clamped_step(self, planned_depth: float, duration: float):
        """Advances the dive, refusing to ascend above the ceiling.

        Parameters:
        -----------
        planned_depth: float
            Depth the plan calls for (meters).
        duration: float
            Length of the step (minutes).

        Returns:
        --------
        actual_depth: float
            Depth actually held, which is the planned depth or the ceiling,
            whichever is deeper.

        Notes:
        ------
        Clamping is what turns an infeasible plan into an executable dive: the
        stops land inline on the ascent rather than being appended after the
        diver has already surfaced.

        """
        self.update_anchor()
        actual_depth = max(planned_depth, self.ceiling)
        self.step(actual_depth, duration)
        return actual_depth

    def can_surface(self, with_gradient_factors: bool = True):
        """Reports whether direct ascent to the surface is permitted.

        Parameters:
        -----------
        with_gradient_factors: bool, optional
            Apply gradient factors (default True). False uses raw Bühlmann.

        Returns:
        --------
        safe: bool
            True when surfacing is allowed.

        """
        if not with_gradient_factors:
            return is_ascent_safe(
                self.tissues,
                target_depth=0.0,
                surface_pressure=self.surface_pressure,
            )
        return is_ascent_safe_gradient_factors(
            self.tissues,
            target_depth=0.0,
            gf_low=self.gf_low,
            gf_high=self.gf_high,
            first_stop_depth=self.anchor,
            surface_pressure=self.surface_pressure,
        )

    def deco_schedule(self, interval: float = 0.5):
        """Returns the stops owed from here, without advancing the dive.

        Parameters:
        -----------
        interval: float, optional
            Time resolution of the walk (minutes, default 0.5).

        Returns:
        --------
        schedule: list of tuples
            Each tuple is (depth, time), deepest first. Empty when nothing is
            owed.

        """
        return calculate_deco_schedule(
            self.tissues,
            gf_low=self.gf_low,
            gf_high=self.gf_high,
            interval=interval,
            gas_fraction=self.gas_fraction,
            surface_pressure=self.surface_pressure,
            anchor=self.anchor,
        )

    def copy(self):
        """Returns an independent copy, safe to advance separately."""
        return DiveState(
            tissues=list(self.tissues),
            anchor=self.anchor,
            clock=self.clock,
            gf_low=self.gf_low,
            gf_high=self.gf_high,
            gas_fraction=self.gas_fraction,
            surface_pressure=self.surface_pressure,
        )
