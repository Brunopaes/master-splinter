"""End-to-end: analyse a dive, persist it, resume, ask the altitude question.

The pieces are covered in isolation elsewhere. What this file covers is the
join - specifically the path a live device walks every time it wakes up, where
a mistake is not a wrong number but a diver modelled as clean.

"""

import json

import pytest

from master_splinter.model.dive_state import DiveState
from master_splinter.processors.altitude_analysis import (
    analyse_altitude_change,
)
from master_splinter.processors.dive_analysis import analyse_profile
from master_splinter.processors.dive_simulation import generate_dive_profile
from master_splinter.utils.state_store import (
    read_state,
    save_tissues,
    state_problem,
)

DIVE = [
    (30, 2, (0.0, 0.0), "descend"),
    (30, 25, (0.0, 0.0), "constant"),
    (0, 3, (0.0, 0.0), "ascend"),
]


@pytest.fixture
def finished_dive():
    """The tissue state a 30 m dive ends on."""
    profile = generate_dive_profile(DIVE)
    return analyse_profile(profile, DiveState.at_surface()).final_state


def test_resumes_the_loading_it_saved(finished_dive, tmp_path):
    state_file = tmp_path / "state.json"
    save_tissues(finished_dive, state_file)

    saved = read_state(state_file)

    assert saved is not None
    assert saved.tissues == pytest.approx(finished_dive.tissues)
    assert saved.surface_pressure == pytest.approx(
        finished_dive.surface_pressure
    )


def test_a_resumed_diver_is_not_a_fresh_one(finished_dive, tmp_path):
    """The whole point of persisting: the next question sees the loading."""
    state_file = tmp_path / "state.json"
    save_tissues(finished_dive, state_file)
    resumed = read_state(state_file)

    loaded = analyse_altitude_change(resumed.tissues, 2400)
    fresh = analyse_altitude_change(DiveState.at_surface().tissues, 2400)

    # A diver straight out of the water tolerates less altitude than one who
    # never dived. If these agreed, the state file would be doing nothing.
    assert loaded.gradient.max_gain < fresh.gradient.max_gain


def test_creates_the_directory_it_is_given(finished_dive, tmp_path):
    """A first run has no state directory yet - an XDG path, say."""
    state_file = tmp_path / "does" / "not" / "exist" / "state.json"

    save_tissues(finished_dive, state_file)

    assert read_state(state_file) is not None


def test_leaves_no_temporary_behind(finished_dive, tmp_path):
    save_tissues(finished_dive, tmp_path / "state.json")

    assert [p.name for p in tmp_path.iterdir()] == ["state.json"]


def test_an_interrupted_write_does_not_destroy_the_previous_state(
    finished_dive, tmp_path
):
    """The failure a battery-powered device actually has.

    The replace is atomic, so a write that dies before it never leaves a torn
    file - the reader still sees the state from the dive before.

    """
    state_file = tmp_path / "state.json"
    save_tissues(finished_dive, state_file)
    intact = read_state(state_file).tissues

    broken = DiveState.at_surface()
    object.__setattr__(broken, "tissues", object())  # unserialisable
    with pytest.raises(TypeError):
        save_tissues(broken, state_file)

    assert read_state(state_file).tissues == pytest.approx(intact)
    assert [p.name for p in tmp_path.iterdir()] == ["state.json"]


def test_corruption_is_distinguishable_from_absence(finished_dive, tmp_path):
    """read_state returns None for both; only state_problem tells them apart.

    A caller that treats None as "no previous dive" will model a loaded diver
    as clean whenever the file is damaged. state_problem is what makes that
    caller correct, so it has to stay reliable.

    """
    absent = tmp_path / "absent.json"
    assert read_state(absent) is None
    assert state_problem(absent) is None

    truncated = tmp_path / "state.json"
    save_tissues(finished_dive, truncated)
    whole = truncated.read_text(encoding="utf-8")
    truncated.write_text(whole[: len(whole) // 2], encoding="utf-8")

    assert read_state(truncated) is None
    assert state_problem(truncated) is not None


def test_a_state_file_from_another_schema_is_refused(tmp_path):
    state_file = tmp_path / "state.json"
    state_file.write_text(
        json.dumps({"version": 1, "tissues": [0.75] * 16}), encoding="utf-8"
    )

    assert read_state(state_file) is None
    assert "schema version" in state_problem(state_file)
