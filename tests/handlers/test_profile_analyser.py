"""End to end tests for the analyser handler and the renderer."""

import json
import random

import pytest

from handlers.profile_analyser import (
    DEFAULT_BOUNDARIES,
    build_parser,
    main,
)
from model.dive_state import DiveState
from processors.dive_analysis import Violation, analyse_profile
from processors.dive_simulation import generate_dive_profile
from utils.plotting import render_dive_report

PROFILE = [
    (30, 2, (0, 0), "descend"),
    (30, 25, (0, 0), "constant"),
    (0, 3, (0, 0), "ascend"),
]


@pytest.fixture
def report():
    return analyse_profile(
        generate_dive_profile(PROFILE), DiveState.at_surface()
    )


def base_args(tmp_path, *extra):
    return [
        "--state-file",
        str(tmp_path / "state.json"),
        "--output",
        str(tmp_path / "graph.png"),
        *extra,
    ]


def test_renders_without_writing_when_no_output(report):
    figure = render_dive_report(report)
    assert figure.axes
    figure.clf()


def test_renders_to_a_file(report, tmp_path):
    destination = tmp_path / "graph.png"
    figure = render_dive_report(report, output_path=destination)
    figure.clf()

    assert destination.exists()
    assert destination.stat().st_size > 0


def test_rendering_an_empty_report_is_refused():
    from processors.dive_analysis import DiveReport

    with pytest.raises(ValueError, match="no samples"):
        render_dive_report(DiveReport())


def test_default_profile_is_the_dive_it_says_it_is():
    """Pins the shipped default profile to the dive its comments describe.

    DEFAULT_BOUNDARIES drifted once - the bottom segment read 60 m under a
    "Stay at 40m" comment, the ascent ladder sat a rung too deep, and the 5 m
    safety stop appeared twice - and the whole suite still passed, because
    nothing asserted on the default dive. The numbers below are the README's.
    """
    random.seed(0)
    report = analyse_profile(
        generate_dive_profile(DEFAULT_BOUNDARIES), DiveState.at_surface()
    )

    # 3 + 15 + 2 + 2 + 2 + 1 + 2 + 5 + 1; a duplicated segment shows up here.
    assert report.planned_runtime == pytest.approx(33.0)
    # 40 m target, +/- 2 m of jitter on the bottom segment.
    assert report.max_depth == pytest.approx(40.0, abs=2.0)
    # A light obligation the staged ascent nearly discharges on its own.
    assert 0.0 < report.total_deco_time < 10.0
    # Deliberately imperfect: it ascends through its own ceiling.
    assert report.findings_of(Violation.CEILING)
    # ...but it is a breathable dive on air, which is the default gas.
    assert not report.findings_of(Violation.MOD_EXCEEDED)


def test_handler_runs_and_saves_state(tmp_path, capsys):
    assert main(base_args(tmp_path, "--fresh")) == 0

    output = capsys.readouterr().out
    assert "Gas: air" in output
    assert "Safe to surface" in output
    assert (tmp_path / "graph.png").exists()

    saved = json.loads((tmp_path / "state.json").read_text())
    assert len(saved["tissues"]) == 16


def test_rendering_leaves_no_figure_registered(tmp_path):
    """figure.clf() cleared the figure but leaked it; plt.close() releases it.

    Harmless for one CLI run, not harmless if main() is ever driven in a loop.
    """
    import matplotlib.pyplot as plt

    plt.close("all")
    assert main(base_args(tmp_path, "--fresh", "--no-save")) == 0
    assert plt.get_fignums() == []


def test_dive_site_is_always_reported(tmp_path, capsys):
    """Both commands name the site in the same words; it is not decoration.

    Every ceiling, M-value and MOD in the report is computed against this
    pressure, so a reader has to be able to see which one was used.
    """
    main(base_args(tmp_path, "--fresh", "--no-save", "--no-graph"))
    assert "Dive site: 0 m (1.0132 bar)" in capsys.readouterr().out


def test_altitude_sets_the_surface_pressure_and_is_saved(tmp_path, capsys):
    """The state file could never hold anything but sea level before this."""
    main(base_args(tmp_path, "--fresh", "--no-graph", "--altitude", "1800"))
    assert "Dive site: 1,800 m (0.8149 bar)" in capsys.readouterr().out

    saved = json.loads((tmp_path / "state.json").read_text())
    assert saved["surface_pressure"] == pytest.approx(0.8149, abs=1e-4)


def test_altitude_increases_the_decompression_obligation(tmp_path, capsys):
    """Less pressure to surface into means more off-gassing owed."""
    main(base_args(tmp_path, "--fresh", "--no-save", "--no-graph"))
    sea_level = capsys.readouterr().out

    main(
        base_args(
            tmp_path,
            "--fresh",
            "--no-save",
            "--no-graph",
            "--altitude",
            "1800",
        )
    )
    mountain = capsys.readouterr().out

    def total(text):
        line = next(ln for ln in text.splitlines() if ln.startswith("  total"))
        return float(line.split()[1])

    assert total(mountain) > total(sea_level)


def test_altitude_overrides_the_saved_site(tmp_path, capsys):
    """The diver has driven somewhere else since the last dive."""
    main(base_args(tmp_path, "--fresh", "--no-graph", "--altitude", "1800"))
    capsys.readouterr()

    main(
        base_args(
            tmp_path,
            "--no-graph",
            "--no-save",
            "--surface-interval",
            "60",
            "--altitude",
            "0",
        )
    )
    assert "Dive site: 0 m (1.0132 bar)" in capsys.readouterr().out


def test_omitting_altitude_keeps_the_saved_site(tmp_path, capsys):
    """Tissues were aged at the saved pressure; reverting would contradict it."""
    main(base_args(tmp_path, "--fresh", "--no-graph", "--altitude", "1800"))
    capsys.readouterr()

    main(
        base_args(
            tmp_path, "--no-graph", "--no-save", "--surface-interval", "60"
        )
    )
    assert "Dive site: 1,800 m (0.8149 bar)" in capsys.readouterr().out


@pytest.mark.parametrize("text", ["abc", "nan", "12000"])
def test_malformed_altitude_is_rejected(text):
    with pytest.raises(SystemExit):
        build_parser().parse_args(["--altitude", text])


def test_no_save_leaves_no_state(tmp_path):
    assert main(base_args(tmp_path, "--fresh", "--no-save")) == 0
    assert not (tmp_path / "state.json").exists()


def test_no_graph_skips_rendering(tmp_path):
    assert main(base_args(tmp_path, "--fresh", "--no-save", "--no-graph")) == 0
    assert not (tmp_path / "graph.png").exists()


def test_second_run_picks_up_residual_loading(tmp_path, capsys):
    main(base_args(tmp_path, "--fresh", "--no-graph"))
    capsys.readouterr()

    main(base_args(tmp_path, "--no-graph", "--surface-interval", "20"))
    output = capsys.readouterr().out
    assert "Residual loading carried over after 20.0 min" in output


def test_fresh_ignores_saved_state(tmp_path, capsys):
    main(base_args(tmp_path, "--fresh", "--no-graph"))
    capsys.readouterr()

    main(base_args(tmp_path, "--fresh", "--no-graph"))
    assert "Residual loading" not in capsys.readouterr().out


def test_nitrox_preset_is_reported_and_flagged(tmp_path, capsys):
    main(
        base_args(
            tmp_path, "--fresh", "--no-save", "--no-graph", "--gas", "ean40"
        )
    )
    output = capsys.readouterr().out
    assert "Gas: ean40 (0.60 N2)" in output
    assert "OXYGEN (MOD)" in output


def test_seed_makes_the_run_reproducible(tmp_path, capsys):
    args = base_args(
        tmp_path, "--fresh", "--no-save", "--no-graph", "--seed", "7"
    )
    main(args)
    first = capsys.readouterr().out
    main(args)
    assert capsys.readouterr().out == first


def test_unwritable_output_exits_nonzero(tmp_path, capsys):
    status = main(
        [
            "--state-file",
            str(tmp_path / "state.json"),
            "--output",
            str(tmp_path / "absent" / "graph.png"),
            "--fresh",
            "--no-save",
        ]
    )
    assert status == 2
    assert "cannot write" in capsys.readouterr().err


def test_unreadable_profile_exits_nonzero(tmp_path, capsys):
    status = main(
        base_args(
            tmp_path,
            "--fresh",
            "--no-save",
            "--no-graph",
            "--profile",
            str(tmp_path / "absent.csv"),
        )
    )
    assert status == 2
    assert "cannot read" in capsys.readouterr().err


def test_out_of_range_nitrogen_fraction_exits_nonzero(tmp_path, capsys):
    status = main(
        base_args(
            tmp_path,
            "--fresh",
            "--no-save",
            "--no-graph",
            "--n2-fraction",
            "1.5",
        )
    )
    assert status == 2
    assert "between 0 and 1" in capsys.readouterr().err


@pytest.mark.parametrize("text", ["1.6", "1.4", "1.2", "0.5"])
def test_ppo2_limits_up_to_the_contingency_limit_parse(text):
    assert build_parser().parse_args(
        ["--ppo2-limit", text]
    ).ppo2_limit == pytest.approx(float(text))


@pytest.mark.parametrize(
    "text", ["1.61", "1.7", "2.0", "0", "-1", "abc", "nan", "inf"]
)
def test_ppo2_limits_above_the_contingency_limit_are_rejected(text):
    """1.6 bar is the hard ceiling; the analyser must not be told otherwise."""
    with pytest.raises(SystemExit):
        build_parser().parse_args(["--ppo2-limit", text])


def test_ppo2_limit_defaults_to_the_working_limit():
    assert build_parser().parse_args([]).ppo2_limit == pytest.approx(1.4)


def test_overridden_ppo2_limit_is_reported_and_applied(tmp_path, capsys):
    """Air at 42 m is ppO2 1.05 bar, which only a lowered limit flags."""
    main(
        base_args(
            tmp_path,
            "--fresh",
            "--no-save",
            "--no-graph",
            "--ppo2-limit",
            "1.0",
        )
    )
    output = capsys.readouterr().out
    assert "Working ppO2 limit: 1.00 bar" in output
    assert "OXYGEN (MOD)" in output


def test_default_ppo2_limit_is_not_printed(tmp_path, capsys):
    """The default run's output is documented in the README verbatim."""
    main(base_args(tmp_path, "--fresh", "--no-save", "--no-graph"))
    assert "Working ppO2 limit" not in capsys.readouterr().out


@pytest.mark.parametrize("text", ["30/85", "50/95", "100/100"])
def test_gradient_factor_pairs_parse(text):
    low, high = build_parser().parse_args(["--gf", text]).gf
    assert 0 < low <= high <= 1.0


@pytest.mark.parametrize("text", ["85", "85/30", "0/85", "abc", "30/101"])
def test_bad_gradient_factor_pairs_are_rejected(text):
    with pytest.raises(SystemExit):
        build_parser().parse_args(["--gf", text])


def test_unusable_state_file_warns_instead_of_starting_fresh_quietly(
    tmp_path, capsys
):
    """Falling back to a clean diver understates the obligation.

    The fallback itself is right - a bad file must not abort an analysis - but
    it errs towards less decompression, so it has to be visible. A diver who
    really is loaded would otherwise read a clean dive with nothing to say
    their residual nitrogen had been discarded.
    """
    path = tmp_path / "state.json"
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "saved_at": "2026-08-28T10:00:00+00:00",
                "surface_pressure": 1.0,
                "gas_fraction": 0.79,
                "tissues": [2.0] * 16,
            }
        )
    )

    assert main(base_args(tmp_path, "--no-graph", "--no-save")) == 0
    output = capsys.readouterr().out
    assert "WARNING" in output
    assert "schema version 1, expected 2" in output
    assert "NOT accounted for" in output


def test_a_missing_state_file_is_not_warned_about(tmp_path, capsys):
    """A first dive is planned from nothing; that is normal, not degraded."""
    assert main(base_args(tmp_path, "--no-graph", "--no-save")) == 0
    assert "WARNING" not in capsys.readouterr().out


def test_fresh_does_not_warn_about_a_state_file_it_was_told_to_ignore(
    tmp_path, capsys
):
    path = tmp_path / "state.json"
    path.write_text("not json at all")

    assert main(base_args(tmp_path, "--no-graph", "--no-save", "--fresh")) == 0
    assert "WARNING" not in capsys.readouterr().out


def test_a_corrupt_state_file_names_what_is_wrong(tmp_path, capsys):
    path = tmp_path / "state.json"
    path.write_text("{ this is not json")

    assert main(base_args(tmp_path, "--no-graph", "--no-save")) == 0
    assert "is not valid JSON" in capsys.readouterr().out


def test_an_absurd_profile_is_reported_not_raised(tmp_path, capsys):
    """The promise is status 2 and a named problem, never a traceback."""
    path = tmp_path / "dive.csv"
    path.write_text("time,depth\n0,0\n5,200\n40,200\n45,0\n")

    assert (
        main(
            base_args(
                tmp_path,
                "--no-graph",
                "--no-save",
                "--fresh",
                "--profile",
                str(path),
            )
        )
        == 2
    )
    assert "check the units" in capsys.readouterr().err


def test_an_unclearable_dive_is_reported_not_raised(tmp_path, capsys):
    """A profile can be in range and still break the model.

    120 m for an hour on air is inside every bound the loader checks and
    cannot be decompressed inside the ascent walk's limit. The model says so
    clearly; the handler's job is to pass that on rather than let a
    RuntimeError out as a traceback.
    """
    path = tmp_path / "dive.csv"
    path.write_text("time,depth\n0,0\n5,120\n65,120\n70,0\n")

    assert (
        main(
            base_args(
                tmp_path,
                "--no-graph",
                "--no-save",
                "--fresh",
                "--profile",
                str(path),
            )
        )
        == 2
    )
    error = capsys.readouterr().err
    assert "cannot analyse" in error
    assert "tissue pressures are likely invalid" in error
