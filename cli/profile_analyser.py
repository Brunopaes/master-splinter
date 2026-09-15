"""Dive profile analyser.

Executes a planned dive profile against the Bühlmann ZHL-16C model, reports
the stops it actually requires and where the plan was unsafe, renders the
result, and carries tissue loading forward to the next dive.

"""

import argparse
import random
import sys
from pathlib import Path

from master_splinter.configs.environment import SURFACE_PRESSURE
from master_splinter.configs.limits import (
    GAS_MIXES,
    MAX_ASCENT_RATE,
    PPO2_CONTINGENCY_LIMIT,
    PPO2_WORKING_LIMIT,
)
from master_splinter.model.atmosphere import (
    elevation_at_pressure,
    pressure_at_elevation,
)
from master_splinter.model.dive_state import DiveState
from master_splinter.processors.dive_analysis import Violation, analyse_profile
from master_splinter.processors.dive_simulation import generate_dive_profile
from cli import validators
from cli.paths import DEFAULT_OUTPUT, default_state_path
from cli.plotting import close_figure, render_dive_report
from master_splinter.utils.profile_loader import (
    ProfileFormatError,
    load_profile,
)
from master_splinter.utils.state_store import (
    load_state,
    save_tissues,
    state_problem,
)

# The reference dive: 40 m for 15 minutes with a staged ascent.
# fmt: off
DEFAULT_BOUNDARIES = [
    (40, 3, (-1.0, 1.0), "descend"),      # Descend to 40m in 3 min
    (40, 15, (-2.0, 2.0), "constant"),    # Stay at 40m for 15 min
    (20, 2, (-0.5, 0.5), "ascend"),       # Ascend to 20m in 2 min
    (20, 2, (-0.5, 0.5), "constant"),     # Hold at 20m for 2 min
    (10, 2, (-0.3, 0.3), "ascend"),       # Ascend to 10m in 2 min
    (10, 1, (-0.2, 0.2), "constant"),     # Hold at 10m for 1 min
    (5, 2, (-0.2, 0.2), "ascend"),        # Ascend to 5m in 2 min
    (5, 5, (-0.1, 0.1), "constant"),      # Safety stop at 5m for 5 min
    (0, 1, (0.0, 0.0), "ascend"),         # Surface in 1 min
]
# fmt: on

VIOLATION_LABEL = {
    Violation.CEILING: "CEILING",
    Violation.ASCENT_RATE: "ASCENT RATE",
    Violation.SURFACED_OWING: "SURFACED OWING",
    Violation.MOD_EXCEEDED: "OXYGEN (MOD)",
}


def build_parser():
    """Builds the command line parser."""
    parser = argparse.ArgumentParser(
        description="Analyse a dive profile against Bühlmann ZHL-16C.",
    )
    parser.add_argument(
        "--profile",
        type=Path,
        help="CSV or JSON dive log; omitted uses the synthetic generator",
    )
    gas = parser.add_mutually_exclusive_group()
    gas.add_argument(
        "--gas",
        choices=sorted(GAS_MIXES),
        default="air",
        help="breathing gas preset (default: air)",
    )
    gas.add_argument(
        "--n2-fraction",
        type=float,
        help="nitrogen fraction, overriding --gas",
    )
    parser.add_argument(
        "--gf",
        type=validators.gradient_factors,
        default="30/85",
        help="gradient factors as LOW/HIGH (default: 30/85)",
    )
    parser.add_argument(
        "--ppo2-limit",
        type=validators.ppo2_limit,
        default=PPO2_WORKING_LIMIT,
        metavar="BAR",
        help=(
            f"working ppO2 limit in bar "
            f"(default: {PPO2_WORKING_LIMIT}, max: {PPO2_CONTINGENCY_LIMIT})"
        ),
    )
    parser.add_argument(
        "--altitude",
        type=validators.elevation,
        default=None,
        metavar="M",
        help=(
            "dive site elevation above sea level in meters (default: 0); "
            "overrides the elevation recorded in the state file"
        ),
    )
    parser.add_argument(
        "--surface-interval",
        type=float,
        help="minutes since the last dive, overriding the wall clock",
    )
    parser.add_argument(
        "--state-file",
        type=Path,
        default=default_state_path(),
        help="tissue state carried between dives",
    )
    parser.add_argument(
        "--no-save",
        action="store_true",
        help="analyse without persisting tissue state",
    )
    parser.add_argument(
        "--fresh",
        action="store_true",
        help="ignore any saved state and start at surface equilibrium",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="graph destination",
    )
    parser.add_argument(
        "--no-graph",
        action="store_true",
        help="skip rendering",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=0,
        help="seed for the synthetic generator (default: 0, reproducible)",
    )
    return parser


def _resolve_start_state(args, gas_fraction):
    """Builds the starting DiveState, applying any saved tissue loading.

    Returns:
    --------
    result: tuple
        (DiveState, surface_interval or None, problem or None). `problem` is
        set only when a state file exists and could not be used, so the caller
        can say so - see the note below.

    Notes:
    ------
    An explicit --altitude wins over the saved surface pressure: the diver has
    driven to a different site since the last dive. Omitting it keeps whatever
    the state file recorded, because the tissues in that file were off-gassed
    at that pressure and resuming at sea level would contradict the ageing.

    An unusable state file falls back to surface equilibrium, which is right -
    a bad file should not abort an analysis - but the fallback errs towards
    *less* decompression, so it is reported rather than applied silently. A
    diver who really is loaded would otherwise be shown a clean dive with
    nothing to indicate their residual nitrogen had been discarded.

    """
    gf_low, gf_high = args.gf
    requested = (
        pressure_at_elevation(args.altitude)
        if args.altitude is not None
        else None
    )

    def fresh_state(surface_pressure):
        return DiveState.at_surface(
            gf_low=gf_low,
            gf_high=gf_high,
            gas_fraction=gas_fraction,
            surface_pressure=surface_pressure,
        )

    if args.fresh:
        return fresh_state(requested or SURFACE_PRESSURE), None, None

    saved = load_state(args.state_file, surface_interval=args.surface_interval)
    if saved is None:
        # Only re-read on the failure path, purely to explain it.
        return (
            fresh_state(requested or SURFACE_PRESSURE),
            None,
            state_problem(args.state_file),
        )

    state, interval = saved
    return (
        DiveState(
            tissues=state.tissues,
            gf_low=gf_low,
            gf_high=gf_high,
            gas_fraction=gas_fraction,
            surface_pressure=(
                requested if requested is not None else state.surface_pressure
            ),
        ),
        interval,
        None,
    )


def _print_report(
    report,
    state,
    gas_name,
    gas_fraction,
    interval,
    ppo2_limit=PPO2_WORKING_LIMIT,
    state_file=None,
    problem=None,
):
    """Writes the human readable summary.

    Notes:
    ------
    The state file warning goes here, in the report body on stdout, rather
    than to stderr. It belongs beside the line it replaces - "Residual loading
    carried over ..." - because the two are alternatives, and a diver reading
    the report needs to see which one they got.

    """
    # Always shown, and in the same words the altitude analyser uses, so the
    # two commands agree about where the dive happened. It is not decoration:
    # every ceiling, M-value and MOD below is computed against this pressure.
    print(
        f"Dive site: {elevation_at_pressure(state.surface_pressure):,.0f} m "
        f"({state.surface_pressure:.4f} bar)"
    )
    print(f"Gas: {gas_name} ({gas_fraction:.2f} N2)")
    print(
        f"Gradient factors: {state.gf_low * 100:.0f}/{state.gf_high * 100:.0f}"
    )
    if ppo2_limit != PPO2_WORKING_LIMIT:
        print(f"Working ppO2 limit: {ppo2_limit:.2f} bar")
    if interval is not None:
        print(
            f"Residual loading carried over after "
            f"{interval:.1f} min at surface"
        )
    if problem is not None:
        print(
            f"WARNING: state file {state_file} {problem}.\n"
            f"         Starting from surface equilibrium - residual loading "
            f"from a previous\n"
            f"         dive is NOT accounted for, so the decompression below "
            f"may be understated.\n"
            f"         Re-run that dive, or pass --fresh to start clean "
            f"deliberately."
        )
    print()

    if report.stops:
        print("Decompression stops performed:")
        for stop in report.stops:
            print(f"  {stop.depth:5.1f} m for {stop.duration:5.1f} min")
        print(f"  total {report.total_deco_time:5.1f} min")
    else:
        print("No decompression stops required.")

    if report.findings:
        print()
        print("Findings:")
        for finding in report.findings:
            label = VIOLATION_LABEL[finding.kind]
            print(f"  [{label}] t={finding.time:.1f} min: {finding.detail}")

    print()
    print(f"Max depth: {report.max_depth:.1f} m")
    print(
        f"Deepest stop required (GF anchor): {report.final_state.anchor:.1f} m"
    )
    print(f"Planned runtime: {report.planned_runtime:.1f} min")
    print(f"Actual runtime: {report.actual_runtime:.1f} min")
    print(f"Safe to surface (no GF): {report.final_state.can_surface(False)}")
    print(f"Safe to surface (with GF): {report.final_state.can_surface()}")


def main(argv=None):
    """Entry point. Returns a process exit status."""
    args = build_parser().parse_args(argv)

    gas_fraction = (
        args.n2_fraction
        if args.n2_fraction is not None
        else GAS_MIXES[args.gas]
    )
    gas_name = "custom" if args.n2_fraction is not None else args.gas
    if not 0.0 < gas_fraction < 1.0:
        print(
            f"error: nitrogen fraction must be between 0 and 1, "
            f"got {gas_fraction}",
            file=sys.stderr,
        )
        return 2

    if args.profile is not None:
        try:
            profile = load_profile(args.profile)
        except (OSError, ProfileFormatError) as error:
            print(
                f"error: cannot read {args.profile}: {error}",
                file=sys.stderr,
            )
            return 2
    else:
        random.seed(args.seed)
        profile = generate_dive_profile(DEFAULT_BOUNDARIES)

    state, interval, problem = _resolve_start_state(args, gas_fraction)
    try:
        report = analyse_profile(
            profile,
            state,
            ascent_rate=MAX_ASCENT_RATE,
            ppo2_limit=args.ppo2_limit,
        )
    except RuntimeError as error:
        # The model's own guards (an ascent that will not clear, a ceiling
        # below the stop grid) already name the problem. They fire on absurd
        # input the loader could not have known was absurd, so report them the
        # way an unreadable profile is reported rather than as a traceback.
        print(
            f"error: cannot analyse {args.profile}: {error}", file=sys.stderr
        )
        return 2

    _print_report(
        report,
        state,
        gas_name,
        gas_fraction,
        interval,
        args.ppo2_limit,
        state_file=args.state_file,
        problem=problem,
    )

    if not args.no_graph:
        try:
            figure = render_dive_report(report, output_path=args.output)
        except OSError as error:
            # Report an unwritable destination the way an unreadable profile
            # is reported, rather than surfacing a matplotlib traceback.
            print(
                f"error: cannot write {args.output}: {error}",
                file=sys.stderr,
            )
            return 2
        print()
        print(f"Graph written to {args.output}")
        close_figure(figure)

    if not args.no_save:
        save_tissues(report.final_state, args.state_file)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
