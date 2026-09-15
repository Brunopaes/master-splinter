"""Tests for altitude exposure after a dive."""

import pytest

from master_splinter.model.atmosphere import elevation_at_pressure
from master_splinter.model.dive_state import DiveState
from master_splinter.model.splinter_decompression import initialize_tissues
from master_splinter.processors.altitude_analysis import (
    analyse_altitude_change,
)
from master_splinter.processors.dive_analysis import analyse_profile
from master_splinter.processors.dive_simulation import generate_dive_profile

CABIN_ALTITUDE = 2400.0  # meters, typical pressurised cabin


@pytest.fixture
def after_a_dive():
    """Tissues of a diver who has *surfaced* from 40 m for 20 minutes.

    A state taken mid-dive is the wrong input here: those tissues cannot
    tolerate sea level either, so every altitude question answers 'no' for a
    reason that has nothing to do with altitude. What gets saved to the state
    file is the post-ascent state, so that is what this exercises.
    """
    profile = generate_dive_profile(
        [
            (40, 3, (0, 0), "descend"),
            (40, 20, (0, 0), "constant"),
            (0, 5, (0, 0), "ascend"),
        ]
    )
    report = analyse_profile(profile, DiveState.at_surface())
    return report.final_state.tissues


def test_a_surfaced_diver_tolerates_sea_level(after_a_dive):
    """The premise every altitude question rests on."""
    assert analyse_altitude_change(after_a_dive, 0.0).safe


def test_descending_is_never_worse_than_staying_put(after_a_dive):
    """Going down raises ambient pressure, which can only help."""
    stay = analyse_altitude_change(after_a_dive, 0.0)
    down = analyse_altitude_change(after_a_dive, -500.0)

    assert down.safe
    assert down.raw.margin > stay.raw.margin
    assert down.raw.wait_minutes == 0.0
    assert down.target_pressure > down.start_pressure


def test_cabin_altitude_straight_off_a_dive_is_refused(after_a_dive):
    report = analyse_altitude_change(after_a_dive, CABIN_ALTITUDE)

    assert not report.safe
    assert report.raw.margin < 0.0
    assert report.raw.wait_minutes > 0.0


def test_slow_compartments_are_what_limit_altitude(after_a_dive):
    """Why flying-after-diving guidance is measured in hours, not minutes."""
    report = analyse_altitude_change(
        after_a_dive, CABIN_ALTITUDE, surface_interval=60.0
    )
    assert report.raw.limiting_half_time >= 100.0


def test_waiting_long_enough_makes_it_safe(after_a_dive):
    report = analyse_altitude_change(after_a_dive, CABIN_ALTITUDE)
    assert analyse_altitude_change(
        after_a_dive,
        CABIN_ALTITUDE,
        surface_interval=report.raw.wait_minutes,
    ).raw.safe


def test_the_reported_wait_is_the_minimum(after_a_dive):
    """A minute less must still be unsafe, or the answer is not the minimum."""
    report = analyse_altitude_change(after_a_dive, CABIN_ALTITUDE)
    assert not analyse_altitude_change(
        after_a_dive,
        CABIN_ALTITUDE,
        surface_interval=report.raw.wait_minutes - 1.0,
    ).raw.safe


def test_gradient_factors_are_never_more_permissive(after_a_dive):
    for interval in (0.0, 120.0, 480.0):
        report = analyse_altitude_change(
            after_a_dive, CABIN_ALTITUDE, surface_interval=interval
        )
        assert report.gradient.wait_minutes >= report.raw.wait_minutes
        assert report.gradient.max_gain <= report.raw.max_gain
        if report.gradient.safe:
            assert report.raw.safe


def test_a_bigger_gain_needs_a_longer_wait(after_a_dive):
    waits = [
        analyse_altitude_change(after_a_dive, gain).raw.wait_minutes
        for gain in (500, 1000, 1500, 2000, 2500)
    ]
    assert waits == sorted(waits)


def test_surface_interval_shortens_the_remaining_wait(after_a_dive):
    fresh = analyse_altitude_change(after_a_dive, CABIN_ALTITUDE)
    rested = analyse_altitude_change(
        after_a_dive, CABIN_ALTITUDE, surface_interval=180.0
    )
    assert rested.raw.wait_minutes < fresh.raw.wait_minutes
    assert rested.raw.max_gain > fresh.raw.max_gain


def test_max_gain_is_the_break_even_point(after_a_dive):
    """Exactly the largest gain that is safe, so a metre more is not."""
    report = analyse_altitude_change(after_a_dive, 0.0)
    gain = report.raw.max_gain

    assert analyse_altitude_change(after_a_dive, gain - 1.0).raw.safe
    assert not analyse_altitude_change(after_a_dive, gain + 1.0).raw.safe


def test_an_unreachable_gain_reports_no_wait_rather_than_hanging():
    """Even at equilibrium the slow compartments cap the tolerable gain."""
    report = analyse_altitude_change(initialize_tissues(), 9000.0)

    assert not report.safe
    assert report.raw.wait_minutes is None


def test_a_rested_diver_can_still_reach_a_useful_altitude():
    report = analyse_altitude_change(initialize_tissues(), 0.0)
    assert 4000.0 < report.raw.max_gain < 7000.0


def test_dive_site_altitude_is_the_baseline_for_the_gain(after_a_dive):
    """The gain is relative to where the dive happened, not to sea level."""
    at_altitude = analyse_altitude_change(
        after_a_dive, 1000.0, surface_pressure=0.8
    )
    assert at_altitude.start_elevation == pytest.approx(
        elevation_at_pressure(0.8)
    )
    assert at_altitude.target_pressure < 0.8
    # A 1000 m gain from a mountain lake ends higher than from the sea, so it
    # is the harder ask despite being the same number of meters.
    from_sea_level = analyse_altitude_change(after_a_dive, 1000.0)
    assert at_altitude.target_pressure < from_sea_level.target_pressure
