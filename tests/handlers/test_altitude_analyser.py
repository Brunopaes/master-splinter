"""End to end tests for the altitude analyser handler."""

import json
from datetime import UTC, datetime

import pytest

from handlers.altitude_analyser import build_parser, main
from model.dive_state import DiveState
from processors.dive_analysis import analyse_profile
from processors.dive_simulation import generate_dive_profile
from utils.state_store import save_tissues

NOW = datetime(2026, 8, 26, 12, 0, tzinfo=UTC)


@pytest.fixture
def state_file(tmp_path):
    """A state file left by a diver who has surfaced from 40 m."""
    profile = generate_dive_profile(
        [
            (40, 3, (0, 0), "descend"),
            (40, 20, (0, 0), "constant"),
            (0, 5, (0, 0), "ascend"),
        ]
    )
    report = analyse_profile(profile, DiveState.at_surface())
    path = tmp_path / "state.json"
    save_tissues(report.final_state, path, now=NOW)
    return path


def run(state_file, *extra):
    return main(["--state-file", str(state_file), *extra])


def test_cabin_altitude_straight_after_surfacing_is_refused(
    state_file, capsys
):
    assert (
        run(state_file, "--elevation-gain", "2400", "--surface-interval", "0")
        == 0
    )
    output = capsys.readouterr().out

    assert "UNSAFE" in output
    assert "raw Bühlmann" in output
    assert "GF 85" in output
    assert "safe in" in output


def test_a_long_surface_interval_clears_it(state_file, capsys):
    assert (
        run(
            state_file,
            "--elevation-gain",
            "2400",
            "--surface-interval",
            "2880",
        )
        == 0
    )
    output = capsys.readouterr().out

    assert "UNSAFE" not in output
    assert output.count("SAFE") == 2


def test_descending_is_permitted(state_file, capsys):
    assert run(state_file, "--elevation-gain", "-500") == 0
    assert "UNSAFE" not in capsys.readouterr().out


def test_output_carries_the_flying_after_diving_caveat(state_file, capsys):
    """The model is more permissive than DAN; saying so is not optional."""
    run(state_file, "--elevation-gain", "2400")
    output = capsys.readouterr().out

    assert "not a substitute" in output
    assert "12 h" in output and "18 h" in output


def test_unreachable_gain_says_so_rather_than_inventing_a_wait(
    state_file, capsys
):
    run(state_file, "--elevation-gain", "9000")
    assert "no surface interval is enough" in capsys.readouterr().out


def test_wall_clock_supplies_the_interval(state_file, capsys):
    """No --surface-interval means the gap since the state was written."""
    run(state_file, "--elevation-gain", "2400")
    output = capsys.readouterr().out
    assert "Surface interval:" in output


def test_dive_site_altitude_is_reported(tmp_path, capsys):
    state = DiveState.at_surface(surface_pressure=0.8)
    path = tmp_path / "alt.json"
    save_tissues(state, path, now=NOW)

    assert main(["--state-file", str(path), "--elevation-gain", "500"]) == 0
    output = capsys.readouterr().out
    assert "Dive site: 1,949 m" in output


def test_altitude_overrides_the_saved_dive_site(state_file, capsys):
    """The gain is measured from the dive site, so the baseline must be settable."""
    assert (
        run(
            state_file,
            "--elevation-gain",
            "600",
            "--altitude",
            "1800",
            "--surface-interval",
            "0",
        )
        == 0
    )
    output = capsys.readouterr().out

    assert "Dive site: 1,800 m (0.8149 bar)" in output
    assert "+600 m -> 2,400 m" in output


def test_the_same_gain_is_harder_from_higher_up(state_file, capsys):
    """600 m from a mountain lake ends where 2,400 m from the sea does."""
    run(state_file, "--elevation-gain", "2400", "--surface-interval", "0")
    from_sea = capsys.readouterr().out

    run(
        state_file,
        "--elevation-gain",
        "600",
        "--altitude",
        "1800",
        "--surface-interval",
        "0",
    )
    from_lake = capsys.readouterr().out

    def target(text):
        line = next(
            ln for ln in text.splitlines() if ln.startswith("Elevation gain")
        )
        return line.split("(")[1].split()[0]

    assert target(from_sea) == target(from_lake)


def test_altitude_round_trips_from_the_profile_analyser(tmp_path, capsys):
    """What module A writes, module B reads, with no flags in between."""
    from handlers.profile_analyser import main as analyse_profile_main

    path = tmp_path / "rt.json"
    analyse_profile_main(
        [
            "--fresh",
            "--no-graph",
            "--altitude",
            "1800",
            "--state-file",
            str(path),
        ]
    )
    capsys.readouterr()

    assert main(["--state-file", str(path), "--elevation-gain", "600"]) == 0
    assert "Dive site: 1,800 m (0.8149 bar)" in capsys.readouterr().out


def test_missing_state_file_exits_nonzero(tmp_path, capsys):
    status = main(
        [
            "--state-file",
            str(tmp_path / "absent.json"),
            "--elevation-gain",
            "2400",
        ]
    )
    assert status == 2
    assert "no usable tissue state" in capsys.readouterr().err


def test_corrupt_state_file_exits_nonzero(tmp_path, capsys):
    path = tmp_path / "bad.json"
    path.write_text(json.dumps({"version": 99}))

    assert main(["--state-file", str(path), "--elevation-gain", "100"]) == 2
    assert "no usable tissue state" in capsys.readouterr().err


def test_elevation_gain_is_required():
    with pytest.raises(SystemExit):
        build_parser().parse_args([])


@pytest.mark.parametrize("text", ["abc", "nan", "inf", "12000", "-99999"])
def test_malformed_elevation_gain_is_rejected(text):
    with pytest.raises(SystemExit):
        build_parser().parse_args(["--elevation-gain", text])


@pytest.mark.parametrize("text", ["0", "-500", "2400", "11000"])
def test_valid_elevation_gains_parse(text):
    assert build_parser().parse_args(
        ["--elevation-gain", text]
    ).elevation_gain == pytest.approx(float(text))
