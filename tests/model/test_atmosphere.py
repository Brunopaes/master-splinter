"""Tests for elevation and ambient pressure conversion."""

import pytest

from configs.environment import ISA_MAX_ELEVATION
from model.atmosphere import elevation_at_pressure, pressure_at_elevation

# International Standard Atmosphere reference points, to 4 decimal places.
# These are the published absolute pressures (101325, 89876, 70121 Pa at 0,
# 1000 and 3000 m), which is only true because SURFACE_PRESSURE is the ISA P0.
# Scaling the same curve through a rounded 1.0 bar would put every one of these
# ~1.3% low and make the name of this fixture a lie.
KNOWN = [
    (0, 1.0132),
    (1000, 0.8987),
    (1800, 0.8149),
    (2400, 0.7563),  # typical pressurised cabin altitude
    (3000, 0.7011),
]


@pytest.mark.parametrize("meters,bar", KNOWN)
def test_matches_the_standard_atmosphere(meters, bar):
    assert pressure_at_elevation(meters) == pytest.approx(bar, abs=5e-5)


@pytest.mark.parametrize("meters", [0, 1, 250, 1800, 2400, 5000, 11000])
def test_round_trips_exactly(meters):
    assert elevation_at_pressure(
        pressure_at_elevation(meters)
    ) == pytest.approx(meters, abs=1e-6)


def test_pressure_falls_with_elevation():
    heights = [0, 500, 1000, 2000, 4000, 8000]
    pressures = [pressure_at_elevation(h) for h in heights]
    assert pressures == sorted(pressures, reverse=True)


def test_below_sea_level_is_denser_than_sea_level():
    """The Dead Sea is a real dive site, 430 m below sea level."""
    assert pressure_at_elevation(-430) > pressure_at_elevation(0)


def test_sea_level_pressure_scales_the_whole_curve():
    assert pressure_at_elevation(2400, sea_level_pressure=2.0) == (
        pytest.approx(2 * pressure_at_elevation(2400, sea_level_pressure=1.0))
    )


def test_above_the_troposphere_is_refused():
    """Past ~11 km the formula silently stops being physics."""
    with pytest.raises(ValueError, match="troposphere"):
        pressure_at_elevation(ISA_MAX_ELEVATION + 1)


@pytest.mark.parametrize("bad", [0.0, -0.5])
def test_non_positive_pressure_is_refused(bad):
    with pytest.raises(ValueError, match="positive"):
        elevation_at_pressure(bad)
