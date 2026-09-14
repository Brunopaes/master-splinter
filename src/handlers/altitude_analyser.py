"""Altitude analyser.

Reads the tissue state left by the last dive and decides whether a given
elevation change is safe after a given surface interval - flying home, driving
over a pass, going back up to a mountain lake.

"""

import argparse
import sys
from pathlib import Path

from model.atmosphere import pressure_at_elevation
from processors.altitude_analysis import analyse_altitude_change
from utils import cli
from utils.state_store import DEFAULT_STATE_PATH, read_state

# Reference exposures, purely for orientation in the output.
CABIN_ALTITUDE = 2400.0


def build_parser():
    """Builds the command line parser."""
    parser = argparse.ArgumentParser(
        description=(
            "Decide whether an elevation change is safe on the tissue state "
            "left by the last dive."
        ),
    )
    parser.add_argument(
        "--elevation-gain",
        type=cli.elevation,
        required=True,
        metavar="M",
        help=(
            "meters to ascend relative to the dive site; negative descends "
            f"(e.g. {CABIN_ALTITUDE:.0f} for a pressurised cabin)"
        ),
    )
    parser.add_argument(
        "--altitude",
        type=cli.elevation,
        default=None,
        metavar="M",
        help=(
            "dive site elevation above sea level in meters; overrides the "
            "elevation recorded in the state file"
        ),
    )
    parser.add_argument(
        "--surface-interval",
        type=float,
        metavar="MIN",
        help="minutes since the last dive, overriding the wall clock",
    )
    parser.add_argument(
        "--gf",
        type=cli.gradient_factors,
        default="30/85",
        help="gradient factors as LOW/HIGH; only HIGH applies here "
        "(default: 30/85)",
    )
    parser.add_argument(
        "--state-file",
        type=Path,
        default=DEFAULT_STATE_PATH,
        help="tissue state left by the last dive",
    )
    return parser


def _format_duration(minutes):
    """Renders minutes as the hours and minutes a diver would plan against."""
    if minutes is None:
        return "no surface interval is enough"
    hours, remainder = divmod(round(max(0.0, minutes)), 60)
    if not hours:
        return f"{remainder} min"
    return f"{hours} h {remainder:02d} min"


def _print_verdict(verdict, surface_interval):
    """Writes one conservatism setting's block."""
    state = "SAFE" if verdict.safe else "UNSAFE"
    print(f"  {verdict.label:<14} {state}")
    print(
        f"    tolerates down to {verdict.tolerated_pressure:.4f} bar "
        f"(compartment {verdict.limiting_compartment}, "
        f"{verdict.limiting_half_time:.0f} min half-time)"
    )
    print(f"    margin {verdict.margin:+.4f} bar")
    if verdict.safe:
        print(f"    room for a further {verdict.max_gain:+,.0f} m")
    else:
        print(f"    safe in {_format_duration(verdict.wait_minutes)}", end="")
        if verdict.wait_minutes:
            total = surface_interval + verdict.wait_minutes
            print(f" ({_format_duration(total)} total surface interval)")
        else:
            print()
        print(f"    largest gain permitted now {verdict.max_gain:+,.0f} m")


def _print_report(report):
    """Writes the human readable summary."""
    print(
        f"Dive site: {report.start_elevation:,.0f} m "
        f"({report.start_pressure:.4f} bar)"
    )
    print(
        f"Elevation gain: {report.elevation_gain:+,.0f} m -> "
        f"{report.start_elevation + report.elevation_gain:,.0f} m "
        f"({report.target_pressure:.4f} bar)"
    )
    print(
        f"Surface interval: {_format_duration(report.surface_interval)} so far"
    )
    print()
    _print_verdict(report.raw, report.surface_interval)
    print()
    _print_verdict(report.gradient, report.surface_interval)
    print()
    print(
        "This models tissue nitrogen only. It is not a substitute for "
        "published\nflying-after-diving guidance, which allows 12 h after a "
        "single no-stop dive\nand 18 h after decompression dives."
    )


def main(argv=None):
    """Entry point. Returns a process exit status."""
    args = build_parser().parse_args(argv)

    saved = read_state(args.state_file)
    if saved is None:
        print(
            f"error: no usable tissue state in {args.state_file}; "
            "run the profile analyser first",
            file=sys.stderr,
        )
        return 2

    interval = (
        args.surface_interval
        if args.surface_interval is not None
        else saved.minutes_since()
    )
    interval = max(0.0, interval)

    # An explicit --altitude overrides the site recorded in the state file,
    # which matters because the gain is measured relative to the dive site.
    surface_pressure = (
        pressure_at_elevation(args.altitude)
        if args.altitude is not None
        else saved.surface_pressure
    )

    _, gf_high = args.gf
    _print_report(
        analyse_altitude_change(
            saved.tissues,
            args.elevation_gain,
            surface_interval=interval,
            gf_high=gf_high,
            surface_pressure=surface_pressure,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
