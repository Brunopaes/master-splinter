"""Tests for the Bühlmann ZHL-16C model itself."""

import pytest

from master_splinter.configs.environment import (
    SEAWATER_METERS_PER_BAR,
    SURFACE_PRESSURE,
)
from master_splinter.configs.limits import STOP_INCREMENT
from master_splinter.configs.zhl16 import (
    WATER_VAPOR_PRESSURE,
    ZHL16_A_VALUES,
    ZHL16_B_VALUES,
    ZHL16_N2_HALF_TIMES,
)
from master_splinter.model.splinter_decompression import (
    _calculate_gf_ceiling_pressure,
    _calculate_maximum_safe_tissue_pressure,
    _calculate_minimum_ambient_pressure,
    calculate_ceiling,
    calculate_deco_schedule,
    calculate_deco_stop,
    initialize_tissues,
    is_ascent_safe,
    limiting_compartment,
    load_gas,
    load_gas_at_pressure,
    tolerated_ambient_pressure,
)

# Surfacing M-values from the published ZHL-16C table, by 0-based index. The
# equations are self-consistent whichever way round a and b are applied, so
# only an external reference catches them being inverted.
#
# Evaluated at exactly 1.0 bar, not at SURFACE_PRESSURE: the published table is
# quoted at a rounded 1 bar surface, and the point of this fixture is to check
# the equations against an outside source rather than against ourselves.
PUBLISHED_SURFACING_M_VALUES = {
    0: 2.9624,
    1: 2.5352,
    7: 1.5223,
    15: 1.2686,
}

# Compartment 4's published b deviates from Bühlmann's generating formula by
# almost exactly 0.01 (0.7825 against a derived 0.7725). Every published table
# and every implementation carries the 0.7825, so it is reproduced rather than
# recomputed - but it has to be excused here or the formula check below fails
# on a value that is deliberately correct.
B_FORMULA_EXCEPTIONS = {3}


def test_b_values_follow_buhlmanns_generating_formula():
    """b = 1.005 - 1/sqrt(halftime), and is identical across 16A/16B/16C.

    A transcription guard, not a physics check. `a` was revised by hand between
    variants and cannot be derived, but `b` never was - so a b-value that does
    not fall out of the half-time is a corrupted table, which is exactly the
    failure a hand-copied coefficient set produces.
    """
    for i, (halftime, b) in enumerate(
        zip(ZHL16_N2_HALF_TIMES, ZHL16_B_VALUES, strict=True)
    ):
        if i in B_FORMULA_EXCEPTIONS:
            continue
        # One rounding unit of the 4-decimal published values: compartment 5
        # derives as 0.81255 and is tabulated 0.8126, exactly on the boundary.
        # Still two orders of magnitude tighter than the smallest corruption
        # this is meant to catch.
        assert b == pytest.approx(1.005 - halftime**-0.5, abs=1e-4), (
            f"compartment {i + 1} (halftime {halftime}) has b={b}, "
            f"formula gives {1.005 - halftime**-0.5:.4f}"
        )


def test_a_values_decrease_monotonically():
    """Slower compartments tolerate less supersaturation, without exception.

    Weaker than the b check above, and deliberately so: `a` was revised by hand
    between variants, so there is no formula to check it against. This catches
    a transposition or an inverted tail but not a plausible-looking wrong
    value - PUBLISHED_SURFACING_M_VALUES is what pins those, and only for the
    four compartments it samples.
    """
    assert ZHL16_A_VALUES == sorted(ZHL16_A_VALUES, reverse=True)
    assert len(set(ZHL16_A_VALUES)) == len(ZHL16_A_VALUES)


def test_initial_loading_subtracts_water_vapor():
    assert initialize_tissues()[0] == pytest.approx(
        0.79 * (SURFACE_PRESSURE - WATER_VAPOR_PRESSURE), abs=1e-6
    )


@pytest.mark.parametrize(
    "index,expected", sorted(PUBLISHED_SURFACING_M_VALUES.items())
)
def test_surfacing_m_values_match_published_table(index, expected):
    assert _calculate_maximum_safe_tissue_pressure(
        index, 1.0
    ) == pytest.approx(expected, abs=1e-3)


def test_m_values_decrease_from_fast_to_slow():
    values = [
        _calculate_maximum_safe_tissue_pressure(i, 1.0) for i in range(16)
    ]
    assert values == sorted(values, reverse=True)


@pytest.mark.parametrize("ambient", [1.0, 2.5, 4.0])
def test_m_value_and_ceiling_are_inverses(ambient):
    for index in range(16):
        m_value = _calculate_maximum_safe_tissue_pressure(index, ambient)
        assert _calculate_minimum_ambient_pressure(
            index, m_value
        ) == pytest.approx(ambient, abs=1e-9)


def test_gf_ceiling_reduces_to_raw_buhlmann_at_gf_one():
    tissues = load_gas(initialize_tissues(), depth=40, time=20)
    for index, pressure in enumerate(tissues):
        assert _calculate_gf_ceiling_pressure(
            index, pressure, 1.0
        ) == pytest.approx(
            _calculate_minimum_ambient_pressure(index, pressure), abs=1e-9
        )


def test_coefficient_tables_are_complete():
    assert len(ZHL16_A_VALUES) == len(ZHL16_B_VALUES) == 16


@pytest.mark.parametrize(
    "depth,low,high",
    [(18, 45, 80), (21, 30, 55), (30, 12, 25), (40, 5, 15)],
)
def test_no_decompression_limits_are_plausible(depth, low, high):
    """NDLs should land near published recreational tables.

    Wide bounds on purpose: these are ZHL-16C with GF 100/100, not DSAT, so
    they will not match a PADI table exactly. The point is to catch an error
    that moves them by an order of magnitude.
    """
    tissues = initialize_tissues()
    ndl = 0.0
    while is_ascent_safe(tissues, target_depth=0.0) and ndl < 300:
        tissues = load_gas(tissues, depth=depth, time=0.5)
        ndl += 0.5
    assert low <= ndl <= high


@pytest.mark.parametrize(
    "depth,minutes", [(50, 40), (60, 30), (40, 60), (30, 90)]
)
def test_schedule_invariants(depth, minutes):
    tissues = load_gas(initialize_tissues(), depth=depth, time=minutes)
    schedule = calculate_deco_schedule(tissues)
    depths = [stop for stop, _ in schedule]

    assert schedule, "a heavily loaded diver should owe stops"
    assert all(stop % STOP_INCREMENT == 0 for stop in depths)
    assert depths == sorted(depths, reverse=True)
    assert len(depths) == len(set(depths)), "each stop appears once"
    assert all(time > 0 for _, time in schedule)


def test_tighter_gradient_factors_are_more_conservative():
    tissues = load_gas(initialize_tissues(), depth=40, time=30)
    loose = calculate_deco_schedule(tissues, gf_low=1.0, gf_high=1.0)
    tight = calculate_deco_schedule(tissues)

    assert tight[0][0] >= loose[0][0], "tighter GF stops deeper"
    assert sum(t for _, t in tight) > sum(t for _, t in loose)


def test_unloaded_diver_owes_nothing():
    assert calculate_deco_schedule(initialize_tissues()) == []
    assert calculate_deco_stop(initialize_tissues()) == (0.0, 0.0)


def test_deco_stop_wrapper_agrees_with_schedule():
    tissues = load_gas(initialize_tissues(), depth=50, time=40)
    schedule = calculate_deco_schedule(tissues)
    first, total = calculate_deco_stop(tissues)

    assert first == schedule[0][0]
    assert total == pytest.approx(sum(t for _, t in schedule))


def test_altitude_requires_more_decompression_than_sea_level():
    """Thinner surface air means a shallower ceiling is reached sooner."""
    sea = load_gas(initialize_tissues(1.0), depth=30, time=30)
    altitude = load_gas(
        initialize_tissues(0.79), depth=30, time=30, surface_pressure=0.79
    )
    at_altitude = calculate_deco_schedule(altitude, surface_pressure=0.79)
    at_sea = calculate_deco_schedule(sea)

    assert sum(t for _, t in at_altitude) > sum(t for _, t in at_sea)


def test_tolerated_pressure_at_gf_one_is_raw_buhlmann():
    """The pressure-domain API must not quietly disagree with the M-values."""
    tissues = load_gas(initialize_tissues(), depth=40.0, time=25.0)
    expected = max(
        _calculate_minimum_ambient_pressure(i, p)
        for i, p in enumerate(tissues)
    )
    assert tolerated_ambient_pressure(tissues, gf=1.0) == pytest.approx(
        expected
    )


def test_calculate_ceiling_is_the_depth_form_of_tolerated_pressure():
    tissues = load_gas(initialize_tissues(), depth=40.0, time=25.0)
    pressure = tolerated_ambient_pressure(tissues, gf=0.30)
    assert calculate_ceiling(tissues, gf=0.30) == pytest.approx(
        max(0.0, (pressure - SURFACE_PRESSURE) * SEAWATER_METERS_PER_BAR)
    )


def test_ceiling_and_tolerated_pressure_default_to_the_same_conservatism():
    """Two names for one limit must not disagree on their default."""
    tissues = load_gas(initialize_tissues(), depth=40.0, time=25.0)
    assert calculate_ceiling(tissues) == pytest.approx(
        max(
            0.0,
            (tolerated_ambient_pressure(tissues) - SURFACE_PRESSURE)
            * SEAWATER_METERS_PER_BAR,
        )
    )


def test_limiting_compartment_is_fast_fresh_and_slow_later():
    """Fast tissues hold a fresh ascent; slow ones hold altitude exposure."""
    fresh = load_gas(initialize_tissues(), depth=40.0, time=25.0)
    rested = load_gas(fresh, depth=0.0, time=60 * 6)

    assert limiting_compartment(fresh) < limiting_compartment(rested)


def test_load_gas_at_pressure_matches_the_depth_form():
    """Depth and pressure are two names for the same step."""
    tissues = initialize_tissues()
    pressure = SURFACE_PRESSURE + 40.0 / SEAWATER_METERS_PER_BAR
    assert load_gas_at_pressure(tissues, pressure, 20.0) == pytest.approx(
        load_gas(tissues, depth=40.0, time=20.0)
    )
