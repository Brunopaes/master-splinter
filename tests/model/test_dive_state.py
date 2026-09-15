"""Tests for the shared dive state machine."""

import pytest

from master_splinter.model.dive_state import DiveState
from master_splinter.model.splinter_decompression import initialize_tissues


def test_at_surface_starts_in_equilibrium():
    state = DiveState.at_surface()
    assert state.tissues == initialize_tissues()
    assert state.clock == 0.0
    assert state.anchor == 0.0


def test_step_advances_the_clock_and_loads_tissues():
    state = DiveState.at_surface()
    before = state.tissues[0]
    state.step(depth=30.0, duration=10.0)

    assert state.clock == 10.0
    assert state.tissues[0] > before


def test_anchor_only_ever_deepens():
    """The anchor must not shallow as fast compartments clear.

    Letting it shallow re-anchors the gradient factor line on whichever stop
    was reached first, and the ceiling can then deepen underneath the diver,
    which reads as a descent partway up the ascent.
    """
    state = DiveState.at_surface()
    state.step(depth=50.0, duration=30.0)
    peak = state.anchor
    assert peak > 0.0

    for _ in range(200):
        state.step(depth=6.0, duration=1.0)
        assert state.anchor >= peak
        peak = state.anchor


def test_clamped_step_never_ascends_above_the_ceiling():
    state = DiveState.at_surface()
    state.step(depth=45.0, duration=30.0)
    assert state.ceiling > 0.0

    actual = state.clamped_step(planned_depth=0.0, duration=1.0)
    assert actual >= state.ceiling - 1e-9
    assert actual > 0.0


def test_clamped_step_follows_the_plan_when_it_is_legal():
    state = DiveState.at_surface()
    actual = state.clamped_step(planned_depth=12.0, duration=1.0)
    assert actual == pytest.approx(12.0)


def test_clamped_step_never_blocks_descent():
    state = DiveState.at_surface()
    state.step(depth=45.0, duration=30.0)
    actual = state.clamped_step(planned_depth=45.0, duration=1.0)
    assert actual == pytest.approx(45.0)


def test_unloaded_diver_can_surface():
    state = DiveState.at_surface()
    assert state.can_surface()
    assert state.can_surface(with_gradient_factors=False)


def test_loaded_diver_cannot_surface():
    state = DiveState.at_surface()
    state.step(depth=45.0, duration=30.0)
    assert not state.can_surface()


def test_copy_is_independent():
    state = DiveState.at_surface()
    clone = state.copy()
    clone.step(depth=40.0, duration=20.0)

    assert state.clock == 0.0
    assert state.tissues == initialize_tissues()
    assert clone.clock == 20.0


def test_deco_schedule_does_not_advance_the_dive():
    state = DiveState.at_surface()
    state.step(depth=45.0, duration=30.0)
    clock, tissues = state.clock, list(state.tissues)

    assert state.deco_schedule()
    assert state.clock == clock
    assert state.tissues == tissues


def test_gas_fraction_changes_loading():
    """Less nitrogen in the mix means less nitrogen in the diver."""
    air = DiveState.at_surface(gas_fraction=0.79)
    ean40 = DiveState.at_surface(gas_fraction=0.60)
    air.step(depth=30.0, duration=30.0)
    ean40.step(depth=30.0, duration=30.0)

    assert ean40.tissues[0] < air.tissues[0]
    assert ean40.ceiling <= air.ceiling
