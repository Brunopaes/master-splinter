"""Tests for profile analysis: executed-dive geometry and plan findings."""

from itertools import pairwise

import pytest

from master_splinter.model.dive_state import DiveState
from master_splinter.model.splinter_decompression import (
    calculate_first_stop_depth,
    calculate_stop_ceiling,
)
from master_splinter.processors.dive_analysis import Violation, analyse_profile
from master_splinter.processors.dive_simulation import generate_dive_profile

DEEP = [
    (50, 4, (0, 0), "descend"),
    (50, 35, (0, 0), "constant"),
    (0, 5, (0, 0), "ascend"),
]
VERY_DEEP = [
    (60, 5, (0, 0), "descend"),
    (60, 25, (0, 0), "constant"),
    (0, 6, (0, 0), "ascend"),
]
RECREATIONAL = [
    (18, 2, (0, 0), "descend"),
    (18, 30, (0, 0), "constant"),
    (5, 2, (0, 0), "ascend"),
    (5, 3, (0, 0), "constant"),
    (0, 1, (0, 0), "ascend"),
]
ENDS_DEEP = [(40, 2, (0, 0), "descend"), (40, 3, (0, 0), "constant")]

ALL_PROFILES = [DEEP, VERY_DEEP, RECREATIONAL, ENDS_DEEP]


def report_for(boundaries, **state_kwargs):
    profile = generate_dive_profile(boundaries)
    return analyse_profile(profile, DiveState.at_surface(**state_kwargs))


@pytest.mark.parametrize("boundaries", ALL_PROFILES)
def test_dive_ends_at_the_surface(boundaries):
    assert report_for(boundaries).samples[-1].actual_depth == pytest.approx(0)


@pytest.mark.parametrize("boundaries", ALL_PROFILES)
def test_clock_is_monotonic(boundaries):
    times = [s.time for s in report_for(boundaries).samples]
    assert times == sorted(times)


@pytest.mark.parametrize("boundaries", ALL_PROFILES)
def test_diver_never_surfaces_and_submerges_again(boundaries):
    """The bug that motivated running deco inline on the ascent.

    Discharging the obligation after the plan had already reached 0 m drew a
    diver who surfaced, went back down to 3 m, and surfaced a second time.
    """
    depths = [s.actual_depth for s in report_for(boundaries).samples]
    surfaced = False
    for depth in depths:
        if depth <= 1e-9:
            surfaced = True
        elif surfaced:
            pytest.fail(f"re-submerged to {depth:.1f} m after surfacing")


@pytest.mark.parametrize("boundaries", ALL_PROFILES)
def test_no_descent_after_the_deepest_point(boundaries):
    """Once the ascent starts, depth must not increase.

    A too-shallow gradient factor anchor lets the ceiling deepen underneath
    the diver, which shows up here as a descent partway up.
    """
    depths = [s.actual_depth for s in report_for(boundaries).samples]
    tail = depths[depths.index(max(depths)) :]
    assert all(a >= b - 1e-9 for a, b in pairwise(tail))


@pytest.mark.parametrize("boundaries", ALL_PROFILES)
def test_stop_markers_sit_on_the_plotted_line(boundaries):
    """Every stop marker must coincide with a sample the renderer draws."""
    report = report_for(boundaries)
    vertices = {
        (round(s.time, 6), round(s.actual_depth, 6)) for s in report.samples
    }
    for stop in report.stops:
        assert (
            round(stop.started_at, 6),
            round(stop.depth, 6),
        ) in vertices


@pytest.mark.parametrize("boundaries", ALL_PROFILES)
def test_stops_are_reported_once_each(boundaries):
    depths = [stop.depth for stop in report_for(boundaries).stops]
    assert len(depths) == len(set(depths))


def test_noisy_plan_does_not_fragment_a_single_stop():
    """A plan oscillating across the ceiling is still one stop per depth."""
    noisy = [
        (40, 3, (0, 0), "descend"),
        (40, 18, (0, 0), "constant"),
        (6, 3, (0, 0), "ascend"),
        (6, 20, (-3.0, 3.0), "constant"),
        (0, 1, (0, 0), "ascend"),
    ]
    depths = [stop.depth for stop in report_for(noisy).stops]
    assert len(depths) == len(set(depths))


def test_final_ascent_respects_the_ascent_rate():
    """A plan ending at depth must not surface in a single step."""
    report = report_for(ENDS_DEEP)
    samples = report.samples
    for previous, current in pairwise(samples):
        span = current.time - previous.time
        if span <= 0:
            continue
        climb = (previous.actual_depth - current.actual_depth) / span
        assert climb <= 10.0 + 1e-6


def test_recreational_dive_owes_nothing():
    report = report_for(RECREATIONAL)
    assert report.stops == []
    assert report.final_state.can_surface()


def test_deep_dive_owes_a_staircase_of_stops():
    report = report_for(DEEP)
    depths = [stop.depth for stop in report.stops]
    assert len(depths) > 3
    assert depths == sorted(depths, reverse=True)
    assert all(depth % 3 == 0 for depth in depths)


def test_runtime_extends_past_the_plan_when_deco_is_owed():
    report = report_for(DEEP)
    assert report.actual_runtime > report.planned_runtime
    assert report.total_deco_time > 0


def test_ceiling_violation_is_reported():
    report = report_for(DEEP)
    findings = report.findings_of(Violation.CEILING)
    assert findings
    assert "ceiling" in findings[0].detail


def test_surfacing_with_an_obligation_is_reported():
    assert report_for(DEEP).findings_of(Violation.SURFACED_OWING)


def test_ascent_rate_violation_is_reported():
    fast = [
        (30, 2, (0, 0), "descend"),
        (30, 10, (0, 0), "constant"),
        (0, 1, (0, 0), "ascend"),
    ]
    findings = report_for(fast).findings_of(Violation.ASCENT_RATE)
    assert findings
    assert "m/min" in findings[0].detail


def test_ascent_at_exactly_the_limit_is_not_flagged():
    """30 m over 3 min is exactly 10 m/min, the recommended rate.

    Floating point puts the computed rate a few ulps above the limit, and
    flagging the recommended rate teaches the reader to ignore findings.
    """
    at_limit = [
        (30, 2, (0, 0), "descend"),
        (30, 25, (0, 0), "constant"),
        (0, 3, (0, 0), "ascend"),
    ]
    assert not report_for(at_limit).findings_of(Violation.ASCENT_RATE)


def test_slow_ascent_is_not_flagged():
    slow = [
        (20, 4, (0, 0), "descend"),
        (20, 10, (0, 0), "constant"),
        (0, 6, (0, 0), "ascend"),
    ]
    assert not report_for(slow).findings_of(Violation.ASCENT_RATE)


def test_sample_jitter_is_not_mistaken_for_an_ascent():
    """Bottom-phase noise must not read as a 20 m/min ascent."""
    jittery = [
        (40, 2, (0, 0), "descend"),
        (40, 15, (-2.0, 2.0), "constant"),
        (0, 6, (0, 0), "ascend"),
    ]
    for finding in report_for(jittery).findings_of(Violation.ASCENT_RATE):
        assert finding.time > 15.0, "flagged jitter during the bottom phase"


def test_oxygen_limit_is_reported_for_nitrox_too_deep():
    """EAN40 at 40 m is ppO2 2.0 bar, well past the 1.6 contingency limit."""
    findings = report_for(ENDS_DEEP, gas_fraction=0.60).findings_of(
        Violation.MOD_EXCEEDED
    )
    assert findings
    assert "MOD" in findings[0].detail


def test_reported_mod_is_the_depth_the_limit_is_reached_at():
    """EAN40's 1.6 bar contingency MOD, the figure in the README.

    29.9 m rather than the round 30.0 m of the tables, because those are quoted
    against a rounded 1 bar surface and this threads the ISA sea level pressure
    through like every other depth in the model.
    """
    finding = report_for(ENDS_DEEP, gas_fraction=0.60).findings_of(
        Violation.MOD_EXCEEDED
    )[0]
    assert "MOD for this mix is 29.9 m" in finding.detail


def test_reported_mod_follows_the_surface_pressure():
    """At altitude a given ppO2 sits deeper, so the MOD is deeper too.

    The conversion used to hardcode sea level and 10 m/bar, which every other
    depth calculation in the model threads through surface_pressure and
    SEAWATER_METERS_PER_BAR.
    """
    finding = report_for(
        ENDS_DEEP, gas_fraction=0.60, surface_pressure=0.8
    ).findings_of(Violation.MOD_EXCEEDED)[0]
    assert "MOD for this mix is 32.0 m" in finding.detail


def test_lowering_the_ppo2_limit_flags_a_dive_the_default_allows():
    """Air at 40 m is ppO2 1.05 bar: fine at 1.4, a breach at 1.0."""
    profile = generate_dive_profile(ENDS_DEEP)
    assert not analyse_profile(profile, DiveState.at_surface()).findings_of(
        Violation.MOD_EXCEEDED
    )

    finding = analyse_profile(
        profile, DiveState.at_surface(), ppo2_limit=1.0
    ).findings_of(Violation.MOD_EXCEEDED)[0]
    assert "exceeds the 1.0 bar limit" in finding.detail
    # (1.0 / 0.21 - SURFACE_PRESSURE) * SEAWATER_METERS_PER_BAR
    assert "MOD for this mix is 37.5 m" in finding.detail


def test_raising_the_ppo2_limit_clears_a_dive_the_default_flags():
    """EAN32 at 35 m is ppO2 1.44 bar: flagged at 1.4, accepted at 1.6.

    35 m rather than 40 m so the exposure sits clear of the 1.6 contingency
    limit; 40 m lands on it to within a rounding error.
    """
    profile = generate_dive_profile(
        [(35, 2, (0, 0), "descend"), (35, 3, (0, 0), "constant")]
    )
    assert analyse_profile(
        profile, DiveState.at_surface(gas_fraction=0.68)
    ).findings_of(Violation.MOD_EXCEEDED)

    assert not analyse_profile(
        profile, DiveState.at_surface(gas_fraction=0.68), ppo2_limit=1.6
    ).findings_of(Violation.MOD_EXCEEDED)


def test_ppo2_limit_does_not_disturb_the_decompression_model():
    """It judges the plan; it must not change the dive that gets executed."""
    profile = generate_dive_profile(ENDS_DEEP)
    default = analyse_profile(profile, DiveState.at_surface())
    lowered = analyse_profile(profile, DiveState.at_surface(), ppo2_limit=0.5)

    assert lowered.total_deco_time == pytest.approx(default.total_deco_time)
    assert lowered.actual_runtime == pytest.approx(default.actual_runtime)
    assert [s.actual_depth for s in lowered.samples] == pytest.approx(
        [s.actual_depth for s in default.samples]
    )


def test_air_at_recreational_depth_has_no_oxygen_finding():
    assert not report_for(RECREATIONAL).findings_of(Violation.MOD_EXCEEDED)


def test_nitrox_needs_less_decompression_than_air():
    """The entire point of nitrox: less inert gas, less obligation."""
    air = report_for(DEEP, gas_fraction=0.79)
    ean40 = report_for(DEEP, gas_fraction=0.60)
    assert ean40.total_deco_time < air.total_deco_time


def test_residual_loading_lengthens_a_repetitive_dive():
    profile = generate_dive_profile(RECREATIONAL)
    first = analyse_profile(profile, DiveState.at_surface())
    repeat = analyse_profile(
        profile, DiveState(tissues=list(first.final_state.tissues))
    )
    assert repeat.total_deco_time > first.total_deco_time


@pytest.mark.parametrize("boundaries", ALL_PROFILES)
def test_the_executed_dive_never_rises_above_its_own_ceiling(boundaries):
    """The clamp's whole claim, asserted rather than assumed.

    analyse_profile exists to turn an infeasible plan into a dive someone
    could actually perform, and every other test here checks a consequence of
    that - the stops it produces, the findings it raises, the runtime. None
    checked the property itself: that at no point in the executed dive is the
    diver shallower than the ceiling their own tissues imply.

    The anchor is rebuilt as a running maximum rather than taken from the
    final state. Sample does not carry it, and the final anchor is the
    deepest one, which widens the gradient factor span, loosens the
    interpolated factor and yields a *shallower* ceiling - a weaker test than
    the one intended. Reconstructing it step by step compares each sample
    against the limit that actually applied at the time.
    """
    report = report_for(boundaries)

    anchor = 0.0
    for sample in report.samples:
        tissues = list(sample.tissues)
        anchor = max(anchor, calculate_first_stop_depth(tissues, gf_low=0.30))
        ceiling = calculate_stop_ceiling(tissues, first_stop_depth=anchor)
        assert sample.actual_depth >= ceiling - 1e-9, (
            f"t={sample.time:.1f} min: diver at {sample.actual_depth:.1f} m "
            f"with a ceiling of {ceiling:.1f} m (anchor {anchor:.1f} m)"
        )
