"""Tests for carrying tissue loading between dives."""

import json
from datetime import UTC, datetime, timedelta

import pytest

from master_splinter.configs.environment import SURFACE_PRESSURE
from master_splinter.model.dive_state import DiveState
from master_splinter.model.splinter_decompression import initialize_tissues
from master_splinter.utils.state_store import (
    SCHEMA_VERSION,
    age_tissues,
    load_state,
    load_tissues,
    read_state,
    save_tissues,
)

NOW = datetime(2026, 8, 26, 12, 0, tzinfo=UTC)


@pytest.fixture
def loaded_state():
    state = DiveState.at_surface()
    state.step(depth=40.0, duration=25.0)
    return state


@pytest.fixture
def state_file(tmp_path):
    return tmp_path / "state.json"


def test_round_trip_with_no_surface_interval(loaded_state, state_file):
    save_tissues(loaded_state, state_file, now=NOW)
    tissues, interval = load_tissues(state_file, now=NOW)

    assert interval == 0.0
    assert tissues == pytest.approx(loaded_state.tissues)


def test_saved_file_is_readable_json(loaded_state, state_file):
    save_tissues(loaded_state, state_file, now=NOW)
    payload = json.loads(state_file.read_text())

    assert payload["version"] == SCHEMA_VERSION
    assert payload["saved_at"] == NOW.isoformat()
    assert len(payload["tissues"]) == 16


def test_anchor_is_not_persisted(loaded_state, state_file):
    """A new dive starts with a fresh gradient factor line.

    Carrying the previous dive's anchor would put the next dive's first stop
    partway up the interpolation, at a factor looser than gf_low.
    """
    assert loaded_state.anchor > 0.0
    save_tissues(loaded_state, state_file, now=NOW)
    assert "anchor" not in json.loads(state_file.read_text())


def test_surface_interval_offgasses(loaded_state, state_file):
    save_tissues(loaded_state, state_file, now=NOW)
    tissues, interval = load_tissues(state_file, now=NOW, surface_interval=60)

    assert interval == 60.0
    assert all(a < b for a, b in zip(tissues, loaded_state.tissues))


def test_long_surface_interval_returns_to_equilibrium(
    loaded_state, state_file
):
    save_tissues(loaded_state, state_file, now=NOW)
    tissues, _ = load_tissues(
        state_file, now=NOW, surface_interval=60 * 24 * 3
    )
    assert tissues == pytest.approx(initialize_tissues(), abs=1e-3)


def test_wall_clock_supplies_the_interval(loaded_state, state_file):
    save_tissues(loaded_state, state_file, now=NOW)
    later = NOW + timedelta(minutes=90)
    _, interval = load_tissues(state_file, now=later)

    assert interval == pytest.approx(90.0)


def test_explicit_interval_overrides_the_wall_clock(loaded_state, state_file):
    save_tissues(loaded_state, state_file, now=NOW)
    later = NOW + timedelta(minutes=90)
    _, interval = load_tissues(state_file, now=later, surface_interval=10)

    assert interval == 10.0


def test_clock_skew_clamps_to_zero(loaded_state, state_file):
    """A timestamp in the future must not ongas the diver at the surface."""
    save_tissues(loaded_state, state_file, now=NOW)
    earlier = NOW - timedelta(hours=5)
    tissues, interval = load_tissues(state_file, now=earlier)

    assert interval == 0.0
    assert tissues == pytest.approx(loaded_state.tissues)


def test_missing_file_returns_none(tmp_path):
    assert load_tissues(tmp_path / "absent.json") is None


@pytest.mark.parametrize(
    "content",
    [
        "",
        "not json at all",
        "[]",
        json.dumps({"version": 99, "tissues": [0.7] * 16}),
        json.dumps({"version": 1, "tissues": [0.7] * 3}),
        json.dumps({"version": 1, "tissues": ["a"] * 16}),
        json.dumps({"version": 1}),
    ],
)
def test_unusable_file_returns_none_rather_than_raising(state_file, content):
    """A corrupt state file must degrade to 'start fresh', never abort."""
    state_file.write_text(content)
    assert load_tissues(state_file) is None


def test_read_state_does_not_age_the_tissues(loaded_state, state_file):
    """The altitude analyser needs the file as saved, then ages it itself."""
    save_tissues(loaded_state, state_file, now=NOW)
    saved = read_state(state_file)

    assert saved.tissues == pytest.approx(loaded_state.tissues)
    assert saved.saved_at == NOW


def test_read_state_carries_pressure_and_gas(state_file):
    state = DiveState.at_surface(surface_pressure=0.8, gas_fraction=0.68)
    save_tissues(state, state_file, now=NOW)
    saved = read_state(state_file)

    assert saved.surface_pressure == pytest.approx(0.8)
    assert saved.gas_fraction == pytest.approx(0.68)


def test_saved_surface_pressure_survives_the_round_trip(state_file):
    """Ageing happens at the logged pressure, so the caller must get it back.

    Off-gassing at 0.8 bar and then resuming the dive at 1.0 bar would
    contradict the ageing that just happened.
    """
    state = DiveState.at_surface(surface_pressure=0.8)
    save_tissues(state, state_file, now=NOW)
    aged, _ = load_state(state_file, now=NOW, surface_interval=60)

    assert aged.surface_pressure == pytest.approx(0.8)


def test_age_tissues_uses_air_not_the_dive_gas(loaded_state):
    """A diver breathes air at the surface whatever they dived on."""
    from master_splinter.configs.limits import N2_FRACTION_AIR
    from master_splinter.model.splinter_decompression import load_gas

    assert age_tissues(loaded_state.tissues, 60.0) == pytest.approx(
        load_gas(
            loaded_state.tissues,
            depth=0.0,
            time=60.0,
            gas_fraction=N2_FRACTION_AIR,
        )
    )


@pytest.mark.parametrize("bad", [None, "abc", float("nan"), float("inf")])
def test_unusable_surface_pressure_falls_back_rather_than_raising(
    state_file, loaded_state, bad
):
    """A null or non-numeric field must not abort the run.

    `payload.get(key, default)` returns None for a key present but null, which
    used to reach load_gas and raise TypeError deep in the model.
    """
    save_tissues(loaded_state, state_file, now=NOW)
    payload = json.loads(state_file.read_text())
    payload["surface_pressure"] = bad
    state_file.write_text(json.dumps(payload))

    aged, interval = load_state(state_file, now=NOW, surface_interval=60)
    assert aged.surface_pressure == pytest.approx(SURFACE_PRESSURE)
    assert interval == 60.0


def test_repetitive_dive_is_more_constrained(loaded_state, state_file):
    save_tissues(loaded_state, state_file, now=NOW)
    tissues, _ = load_tissues(state_file, now=NOW, surface_interval=30)
    repeat = DiveState(tissues=tissues)

    assert repeat.ceiling >= DiveState.at_surface().ceiling
    assert repeat.tissues[15] > initialize_tissues()[15]
