"""Bühlmann ZHL-16C Decompression Model Splinter Implementation."""

import math

from configs.environment import SEAWATER_METERS_PER_BAR, SURFACE_PRESSURE
from configs.limits import N2_FRACTION_AIR, STOP_INCREMENT
from configs.zhl16 import (
    WATER_VAPOR_PRESSURE,
    ZHL16_A_VALUES,
    ZHL16_B_VALUES,
    ZHL16_N2_HALF_TIMES,
)

# Defensive bound on the per-stop simulation loop. The ascent is provably
# finite (see calculate_deco_schedule), so tripping this means the inputs are
# wrong, not that the dive is long. At the default 0.5 min step this allows a
# 12 hour stop before giving up.
_MAX_STOP_ITERATIONS = 1440


def initialize_tissues(pressure_surface: float = SURFACE_PRESSURE):
    """Initializes tissue compartments with nitrogen pressures
    at surface equilibrium.

    Parameters:
    -----------
    pressure_surface: float
        Surface pressure in Bar (default is 1.01325 Bar, sea level).

    Returns:
    --------
    tissues: list
        List of initial tissue nitrogen pressures (in Bar).

    Notes:
    ------
    Tissues start in equilibrium with the alveolar nitrogen pressure, not
    with dry air, so the water vapor pressure in the lungs is subtracted
    from the surface pressure before applying N2_FRACTION_AIR:

        p_tissue(0) = N2_FRACTION_AIR * (pressure_surface - P_H2O)

    At sea level (1.01325 Bar) this gives ~0.7509 Bar. Texts that quote the
    Bühlmann convention as ~0.7405 Bar are evaluating the same expression at a
    rounded 1.0 Bar surface; the equilibrium tracks the real surface pressure,
    which is what a dive computer reads off its barometer.

    """
    # Initial N2 pressure in tissues (assuming equilibrium with surface air)
    return [N2_FRACTION_AIR * (pressure_surface - WATER_VAPOR_PRESSURE)] * 16


def _calculate_minimum_ambient_pressure(i, p_tissue):
    """Calculates the minimum ambient pressure for a given tissue compartment
    to avoid decompression sickness.

    Parameters:
    -----------
    i: int
        Tissue compartment index (0-15).
    p_tissue: float
        Current tissue nitrogen pressure (in Bar).

    Returns:
    --------
    min_ambient_pressure: float
        Minimum ambient pressure to avoid decompression sickness (in Bar).

    Notes:
    ------
    min_ambient_pressure = (p_tissue - a) * b

    This is the inverse of the M-value equation
    m_value = ambient_pressure / b + a.

    """
    a = ZHL16_A_VALUES[i]
    b = ZHL16_B_VALUES[i]
    return (p_tissue - a) * b


def _calculate_maximum_safe_tissue_pressure(i, ambient_pressure):
    """Calculates the maximum safe tissue pressure (M-value) for a given tissue
    compartment at a specific ambient pressure.

    Parameters:
    -----------
    i: int
        Tissue compartment index (0-15).
    ambient_pressure: float
        Current ambient pressure (in Bar).

    Returns:
    --------
    m_value: float
        Maximum safe tissue pressure (M-value) for the compartment (in Bar).

    Notes:
    ------
    M-value = ambient_pressure / b + a

    In ZHL-16 the b coefficient divides the ambient pressure; it does not
    multiply it. At sea level this yields ~2.99 Bar for compartment 1; the
    ~2.96 Bar of the published ZHL-16C table is the same expression evaluated
    at a rounded 1.0 Bar surface.

    """
    a = ZHL16_A_VALUES[i]
    b = ZHL16_B_VALUES[i]
    return ambient_pressure / b + a


def _calculate_ambient_pressure(
    depth: float,
    surface_pressure: float = SURFACE_PRESSURE,
):
    """Calculates ambient pressure in Bar at a given depth in meters.

    Parameters:
    -----------
    depth: float
        Depth of the dive (in meters).
    surface_pressure: float, optional
        Ambient pressure at the surface (in Bar, default 1.01325). Lower
        this for altitude diving.

    Returns:
    --------
    ambient_pressure: float
        Ambient pressure at the given depth (in Bar).

    Notes:
    ------
    ambient_pressure = surface_pressure + depth / SEAWATER_METERS_PER_BAR

    """
    return surface_pressure + (depth / SEAWATER_METERS_PER_BAR)


def _calculate_gf_ceiling_pressure(i, p_tissue, gf):
    """Calculates the lowest ambient pressure a compartment tolerates at a
    fixed gradient factor.

    Parameters:
    -----------
    i: int
        Tissue compartment index (0-15).
    p_tissue: float
        Current tissue nitrogen pressure (in Bar).
    gf: float
        Gradient factor to apply (0.0 to 1.0).

    Returns:
    --------
    ceiling_pressure: float
        Lowest tolerated ambient pressure (in Bar).

    Notes:
    ------
    Solving p_tissue <= P_amb + gf * (M(P_amb) - P_amb) for P_amb, with
    M(P_amb) = P_amb / b + a, gives:

        P_amb >= (p_tissue - gf * a) / (1 + gf * (1 / b - 1))

    At gf = 1.0 this reduces to the raw Bühlmann (p_tissue - a) * b.

    """
    a = ZHL16_A_VALUES[i]
    b = ZHL16_B_VALUES[i]
    return (p_tissue - gf * a) / (1.0 + gf * (1.0 / b - 1.0))


def _calculate_gf_limit(
    i,
    ambient_pressure,
    gf_low,
    gf_high,
    first_stop_pressure,
    surface_pressure: float = SURFACE_PRESSURE,
):
    """Calculates the Gradient Factor limit for a given tissue compartment.

    Parameters:
    -----------
    i: int
        Tissue compartment index (0-15).
    ambient_pressure: float
        Current ambient pressure (in Bar).
    gf_low: float
        Gradient factor at the first stop depth (0.0 to 1.0).
    gf_high: float
        Gradient factor at the surface (0.0 to 1.0).
    first_stop_pressure: float
        Ambient pressure at the first stop depth (in Bar).
    surface_pressure: float, optional
        Ambient pressure at the surface (in Bar, default 1.01325).

    Returns:
    --------
    gf_limit: float
        The allowed tissue pressure limit based on Gradient Factors.

    """
    # Calculate M-value at current ambient pressure
    m_value = _calculate_maximum_safe_tissue_pressure(i, ambient_pressure)

    # Interpolate GF: gf_low at the first stop, gf_high at the surface. At or
    # below the first stop the factor is clamped to gf_low.
    span = first_stop_pressure - surface_pressure
    if span <= 0.0:
        # No decompression obligation, so the surfacing factor applies
        # throughout. Also guards the division below.
        gf = gf_high
    elif ambient_pressure >= first_stop_pressure:
        gf = gf_low
    else:
        gf = gf_high - (gf_high - gf_low) * (
            (ambient_pressure - surface_pressure) / span
        )

    # Calculate the allowed tissue pressure limit
    return ambient_pressure + gf * (m_value - ambient_pressure)


def load_gas(
    tissues,
    depth,
    time,
    gas_fraction: float = N2_FRACTION_AIR,
    surface_pressure: float = SURFACE_PRESSURE,
):
    """Simulates gas loading in tissues over a given time at a specific depth
    using Bühlmann ZHL-16 model.

    Parameters:
    -----------
    tissues: list
        List of tissue nitrogen pressures.
    depth: float
        Depth of the dive (in meters).
    time: float
        Time spent at the given depth (in minutes).
    gas_fraction: float, optional
        Fraction of nitrogen in the breathing gas (default is 0.79 for air).
    surface_pressure: float, optional
        Ambient pressure at the surface (in Bar, default 1.01325).

    Returns:
    --------
    updated: list
        List of updated tissue nitrogen pressures.

    """
    return load_gas_at_pressure(
        tissues,
        _calculate_ambient_pressure(depth, surface_pressure),
        time,
        gas_fraction=gas_fraction,
    )


def load_gas_at_pressure(
    tissues,
    ambient_pressure: float,
    time: float,
    gas_fraction: float = N2_FRACTION_AIR,
):
    """Simulates gas loading in tissues at a given ambient pressure.

    Parameters:
    -----------
    tissues: list
        List of tissue nitrogen pressures.
    ambient_pressure: float
        Ambient pressure the diver is breathing at (in Bar).
    time: float
        Time spent at that pressure (in minutes).
    gas_fraction: float, optional
        Fraction of nitrogen in the breathing gas (default is 0.79 for air).

    Returns:
    --------
    updated: list
        List of updated tissue nitrogen pressures.

    Notes:
    ------
    The primitive load_gas is expressed in. Tissues respond to pressure, not to
    depth: 0.75 bar is 0.75 bar whether the diver reached it by surfacing or by
    boarding an aircraft. Taking pressure directly lets a caller drive the
    model from either.

    """
    inspired_n2 = gas_fraction * (ambient_pressure - WATER_VAPOR_PRESSURE)

    updated: list = []
    for i, p0 in enumerate(tissues):
        halftime = ZHL16_N2_HALF_TIMES[i]
        k = math.log(2) / halftime
        p = p0 + (inspired_n2 - p0) * (1 - math.exp(-k * time))
        updated.append(p)
    return updated


def is_ascent_safe(
    tissues,
    target_depth: float = 0.0,
    surface_pressure: float = SURFACE_PRESSURE,
):
    """Checks if it's safe to ascend to the given target depth
    under Bühlmann ZHL-16 without Gradient Factors.

    Parameters:
    -----------
    tissues: list
        List of tissue nitrogen pressures.
    target_depth: float
        Target depth to ascend to (in meters).
    surface_pressure: float, optional
        Ambient pressure at the surface (in Bar, default 1.01325).

    Returns:
    --------
    safe: bool
        Boolean Expression indicating if it's safe to ascend.
        True if safe, False otherwise.

    """
    ambient_pressure = _calculate_ambient_pressure(
        target_depth, surface_pressure
    )
    for i, p in enumerate(tissues):
        if ambient_pressure < _calculate_minimum_ambient_pressure(i, p):
            return False
    return True


def calculate_ceiling(
    tissues,
    gf: float = 1.0,
    surface_pressure: float = SURFACE_PRESSURE,
):
    """Calculates the current decompression ceiling in meters.

    Parameters:
    -----------
    tissues: list
        List of tissue nitrogen pressures.
    gf: float, optional
        Gradient factor to apply (default 1.0, i.e. raw Bühlmann).
    surface_pressure: float, optional
        Ambient pressure at the surface (in Bar, default 1.01325).

    Returns:
    --------
    ceiling: float
        Shallowest depth the diver can currently ascend to (in meters).
        0.0 means direct ascent to the surface is allowed.

    Notes:
    ------
    The default matches tolerated_ambient_pressure, its pressure-domain twin:
    two names for one limit must not disagree on how conservative they are by
    default. Raw Bühlmann is also the only defensible default for a model
    function - a gradient factor is a conservatism choice, and those live in
    limits.py, not in a signature here. Callers wanting gf_low pass it.

    """
    ceiling = (
        tolerated_ambient_pressure(tissues, gf=gf) - surface_pressure
    ) * SEAWATER_METERS_PER_BAR
    return max(0.0, ceiling)


def tolerated_ambient_pressure(tissues, gf: float = 1.0):
    """Lowest ambient pressure the whole tissue set tolerates right now.

    Parameters:
    -----------
    tissues: list
        List of tissue nitrogen pressures.
    gf: float, optional
        Gradient factor to apply (default 1.0, i.e. raw Bühlmann).

    Returns:
    --------
    pressure: float
        Lowest tolerated ambient pressure (in Bar).

    Notes:
    ------
    The pressure-domain twin of calculate_ceiling, which expresses the same
    limit as a depth below a given surface. Pressure is the model's real
    currency: a diver ascending and a diver driving to altitude are both just
    reducing ambient pressure, so the altitude analysis and the deco ceiling
    come from this one function.

    The maximum across compartments, not the minimum - the diver is held by
    whichever tissue tolerates the least.

    """
    return max(
        _calculate_gf_ceiling_pressure(i, p, gf) for i, p in enumerate(tissues)
    )


def limiting_compartment(tissues, gf: float = 1.0):
    """Index of the compartment that sets the current ceiling.

    Parameters:
    -----------
    tissues: list
        List of tissue nitrogen pressures.
    gf: float, optional
        Gradient factor to apply (default 1.0, i.e. raw Bühlmann).

    Returns:
    --------
    index: int
        0-based compartment index. Fast compartments limit a fresh ascent;
        slow ones limit altitude exposure hours after the dive.

    """
    return max(
        range(len(tissues)),
        key=lambda i: _calculate_gf_ceiling_pressure(i, tissues[i], gf),
    )


def ambient_pressure_at_depth(
    depth: float,
    surface_pressure: float = SURFACE_PRESSURE,
):
    """Ambient pressure at a depth below the surface (in Bar).

    Notes:
    ------
    Public name for the depth conversion. atmosphere.pressure_at_elevation is
    the same conversion in the other direction.

    """
    return _calculate_ambient_pressure(depth, surface_pressure)


def calculate_first_stop_depth(
    tissues,
    gf_low: float = 0.30,
    surface_pressure: float = SURFACE_PRESSURE,
):
    """Calculates the depth of the first (deepest) required decompression stop.

    Parameters:
    -----------
    tissues: list
        List of tissue nitrogen pressures.
    gf_low: float, optional
        Gradient factor at the first stop depth (default 0.30).
    surface_pressure: float, optional
        Ambient pressure at the surface (in Bar, default 1.01325).

    Returns:
    --------
    first_stop_depth: float
        Depth of the first stop (in meters), rounded up to STOP_INCREMENT.
        0.0 when no decompression stop is required.

    Notes:
    ------
    gf_low is used here because, by definition, gf_low is the factor that
    applies at the first stop. This breaks the circularity in the gradient
    factor line, which needs a first stop depth to interpolate against but
    is also what determines that depth.

    """
    ceiling = calculate_ceiling(
        tissues, gf=gf_low, surface_pressure=surface_pressure
    )
    if ceiling <= 0.0:
        return 0.0
    return math.ceil(ceiling / STOP_INCREMENT) * STOP_INCREMENT


def is_ascent_safe_gradient_factors(
    tissues,
    target_depth: float = 0.0,
    gf_low: float = 0.30,
    gf_high: float = 0.85,
    first_stop_depth: float | None = None,
    surface_pressure: float = SURFACE_PRESSURE,
):
    """Checks if it's safe to ascend to the given target depth
    under Bühlmann ZHL-16 with Gradient Factors. It uses typical
    values for gf_low and gf_high.

    Parameters:
    -----------
    tissues: list
        List of tissue nitrogen pressures.
    target_depth: float
        Target depth to ascend to (in meters).
    gf_low: float, optional
        Gradient factor at the first stop depth (default is 0.30).
    gf_high: float, optional
        Gradient factor at the surface (default is 0.85).
    first_stop_depth: float or None, optional
        Depth the gf_low end of the gradient factor line is anchored to. When
        None (the default) it is derived from the tissues themselves, which is
        almost always what is wanted; passing a fixed depth silently mis-scales
        the whole gradient factor line. Pass an explicit value only to keep the
        anchor stable across the steps of a single ascent.
    surface_pressure: float, optional
        Ambient pressure at the surface (in Bar, default 1.01325).

    Returns:
    --------
    safe: bool
        Boolean Expression indicating if it's safe to ascend.
        True if safe, False otherwise.

    """
    if first_stop_depth is None:
        first_stop_depth = calculate_first_stop_depth(
            tissues, gf_low=gf_low, surface_pressure=surface_pressure
        )

    ambient_pressure = _calculate_ambient_pressure(
        target_depth, surface_pressure
    )
    first_stop_pressure = _calculate_ambient_pressure(
        first_stop_depth, surface_pressure
    )

    for i, p_tissue in enumerate(tissues):
        gf_limit = _calculate_gf_limit(
            i,
            ambient_pressure,
            gf_low,
            gf_high,
            first_stop_pressure,
            surface_pressure,
        )
        if p_tissue > gf_limit:
            return False
    return True


def calculate_stop_ceiling(
    tissues,
    gf_low: float = 0.30,
    gf_high: float = 0.85,
    first_stop_depth: float | None = None,
    surface_pressure: float = SURFACE_PRESSURE,
    max_depth: float = 120.0,
):
    """Calculates the shallowest stop-grid depth the diver may ascend to now.

    Parameters:
    -----------
    tissues: list
        List of tissue nitrogen pressures.
    gf_low: float, optional
        Gradient factor at the first stop depth (default 0.30).
    gf_high: float, optional
        Gradient factor at the surface (default 0.85).
    first_stop_depth: float or None, optional
        Anchor for the gradient factor line. Derived from the tissues
        when None.
    surface_pressure: float, optional
        Ambient pressure at the surface (in Bar, default 1.01325).
    max_depth: float, optional
        Deepest grid depth to consider (meters, default 120.0).

    Returns:
    --------
    ceiling: float
        Shallowest permitted depth, rounded to STOP_INCREMENT. 0.0 means direct
        ascent to the surface is allowed.

    Raises:
    -------
    RuntimeError
        If no depth down to max_depth is permitted.

    Notes:
    ------
    calculate_ceiling applies one fixed gradient factor; this walks the actual
    stop grid so the depth-interpolated factor is respected, which is what a
    diver on the way up is really limited by.

    """
    if first_stop_depth is None:
        first_stop_depth = calculate_first_stop_depth(
            tissues, gf_low=gf_low, surface_pressure=surface_pressure
        )

    for n in range(int(max_depth / STOP_INCREMENT) + 1):
        depth = n * STOP_INCREMENT
        if is_ascent_safe_gradient_factors(
            tissues,
            target_depth=depth,
            gf_low=gf_low,
            gf_high=gf_high,
            first_stop_depth=first_stop_depth,
            surface_pressure=surface_pressure,
        ):
            return depth

    raise RuntimeError(
        f"No permitted depth above {max_depth:.0f} m; tissue pressures are "
        "likely invalid."
    )


def walk_ceiling_to_surface(
    tissues,
    gf_low: float = 0.30,
    gf_high: float = 0.85,
    interval: float = 0.5,
    gas_fraction: float = N2_FRACTION_AIR,
    surface_pressure: float = SURFACE_PRESSURE,
    anchor: float = 0.0,
):
    """Walks the decompression ceiling up to the surface, one step at a time.

    Parameters:
    -----------
    tissues: list
        List of tissue nitrogen pressures.
    gf_low: float, optional
        Gradient factor at the first stop depth (default 0.30).
    gf_high: float, optional
        Gradient factor at the surface (default 0.85).
    interval: float, optional
        Time step spent at each ceiling depth (minutes, default 0.5).
    gas_fraction: float, optional
        Fraction of nitrogen in the breathing gas (default is 0.79 for air).
    surface_pressure: float, optional
        Ambient pressure at the surface (in Bar, default 1.01325).
    anchor: float, optional
        Starting value for the gradient factor anchor (meters, default 0.0).
        Pass the deepest stop already required by the dive so far.

    Yields:
    -------
    (depth, interval, tissues, anchor): tuple
        One step of the ascent. `tissues` is the updated list after spending
        `interval` at `depth`; callers must carry it forward themselves.
        Stops yielding once direct ascent to the surface is permitted.

    Raises:
    -------
    RuntimeError
        If the ascent does not clear within _MAX_STOP_ITERATIONS steps.

    Notes:
    ------
    This is the single implementation of the ascent. calculate_deco_schedule
    aggregates it into stops for planning, and the simulation consumes it step
    by step for rendering, so the two can never disagree.

    Termination: holding at depth d drives every compartment toward the
    inspired pressure there, 0.79 * (P_amb(d) - P_H2O), which is always
    strictly below the ambient pressure one STOP_INCREMENT shallower and
    therefore below that depth's gradient factor limit. So the ceiling always
    eventually rises. Demanding the *surface* limit from a deep stop, by
    contrast, can be unsatisfiable.

    The anchor only ever deepens. Letting it shallow would freeze the gradient
    factor line at whichever stop was reached first, and the ceiling could then
    deepen underneath the diver, which reads as a descent partway up.

    """
    steps = 0
    while True:
        anchor = max(
            anchor,
            calculate_first_stop_depth(
                tissues, gf_low=gf_low, surface_pressure=surface_pressure
            ),
        )
        ceiling = calculate_stop_ceiling(
            tissues,
            gf_low=gf_low,
            gf_high=gf_high,
            first_stop_depth=anchor,
            surface_pressure=surface_pressure,
        )
        if ceiling <= 0.0:
            return

        steps += 1
        if steps > _MAX_STOP_ITERATIONS:
            raise RuntimeError(
                f"Ascent did not clear within "
                f"{_MAX_STOP_ITERATIONS * interval:.0f} minutes; "
                "tissue pressures are likely invalid."
            )

        tissues = load_gas(
            tissues,
            depth=ceiling,
            time=interval,
            gas_fraction=gas_fraction,
            surface_pressure=surface_pressure,
        )
        yield ceiling, interval, tissues, anchor


def calculate_deco_schedule(
    tissues,
    gf_low: float = 0.30,
    gf_high: float = 0.85,
    interval: float = 0.5,
    gas_fraction: float = N2_FRACTION_AIR,
    surface_pressure: float = SURFACE_PRESSURE,
    anchor: float = 0.0,
):
    """Calculates the full decompression stop schedule for a given tissue
    loading using gradient factors.

    Parameters:
    -----------
    tissues: list
        List of tissue nitrogen pressures.
    gf_low: float, optional
        Gradient factor at the first stop depth (default 0.30).
    gf_high: float, optional
        Gradient factor at the surface (default 0.85).
    interval: float, optional
        Time step for simulating offgassing at each stop (minutes,
        default 0.5).
    gas_fraction: float, optional
        Fraction of nitrogen in the breathing gas (default is 0.79 for air).
    surface_pressure: float, optional
        Ambient pressure at the surface (in Bar, default 1.01325).
    anchor: float, optional
        Deepest stop already required by the dive so far (meters, default 0.0).

    Returns:
    --------
    schedule: list of tuples
        Each tuple is (depth, time) for one stop, in meters and minutes,
        ordered deepest first. Empty when no decompression is required.

    Notes:
    ------
    A thin aggregation over walk_ceiling_to_surface. Consecutive steps at the
    same depth are merged, so one stop is reported once rather than per step.

    """
    schedule: list[tuple[float, float]] = []
    for depth, step_time, _, _ in walk_ceiling_to_surface(
        tissues,
        gf_low=gf_low,
        gf_high=gf_high,
        interval=interval,
        gas_fraction=gas_fraction,
        surface_pressure=surface_pressure,
        anchor=anchor,
    ):
        if schedule and schedule[-1][0] == depth:
            schedule[-1] = (depth, schedule[-1][1] + step_time)
        else:
            schedule.append((depth, step_time))
    return schedule


def calculate_deco_stop(
    tissues,
    gf_low: float = 0.30,
    gf_high: float = 0.85,
    interval: float = 0.5,
    gas_fraction: float = N2_FRACTION_AIR,
    surface_pressure: float = SURFACE_PRESSURE,
):
    """Calculates the first stop and the total decompression time.

    Parameters:
    -----------
    tissues: list
        List of tissue nitrogen pressures.
    gf_low: float, optional
        Gradient factor at the first stop depth (default 0.30).
    gf_high: float, optional
        Gradient factor at the surface (default 0.85).
    interval: float, optional
        Time step for simulating offgassing at each stop (minutes,
        default 0.5).
    gas_fraction: float, optional
        Fraction of nitrogen in the breathing gas (default is 0.79 for air).
    surface_pressure: float, optional
        Ambient pressure at the surface (in Bar, default 1.01325).

    Returns:
    --------
    deco_stop_depth: float
        Depth of the first stop (meters), 0.0 when none is required.
    total_deco_time: float
        Total time across *all* stops before surfacing is safe (minutes).

    Notes:
    ------
    Convenience wrapper over calculate_deco_schedule for callers that only
    want a headline figure. The returned time covers the whole ascent, not
    just the first stop, so it cannot be fed back into load_gas at
    deco_stop_depth; use calculate_deco_schedule for that.

    """
    schedule = calculate_deco_schedule(
        tissues,
        gf_low=gf_low,
        gf_high=gf_high,
        interval=interval,
        gas_fraction=gas_fraction,
        surface_pressure=surface_pressure,
    )
    if not schedule:
        return 0.0, 0.0
    return schedule[0][0], sum(time for _, time in schedule)
