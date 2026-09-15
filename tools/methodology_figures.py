"""Regenerates the explanatory figures used in the Methodology README.

Every number plotted here is computed by the same functions the analyser
runs, so a figure cannot drift away from the model it illustrates. The
figures this replaced had done exactly that: they showed a 4 minute
compartment 1 (ZHL-16A), an M-value of A + B * P_ambient, and gradient
factor lines drawn above the M-value rather than below it.

Dark theme only, from master_splinter.theme - the style sheet dresses the
canvas and the colour roles name what carries meaning, so a compartment
keeps its hue from here to a dive report.

Lives outside src/ because src/ is the distributable: `pip install
master-splinter` puts exactly one name on the path, master_splinter, and a
script that redraws README figures is not something an installer of the
library should receive. The style sheet and palette live here for the same
reason - once the dive report renderer moved out of the library, nothing
inside it had any use for a colour.

Usage:
------
    pip install -e . && python tools/methodology_figures.py [--output DIR]

"""

import argparse
from pathlib import Path

import matplotlib

# Chosen before pyplot is imported: this script only ever renders to
# files, and there is no display to talk to.
matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]

from master_splinter import theme  # noqa: E402
from master_splinter.configs.zhl16 import ZHL16_N2_HALF_TIMES  # noqa: E402
from master_splinter.model.dive_state import DiveState  # noqa: E402
from master_splinter.model.splinter_decompression import (  # noqa: E402
    _calculate_gf_limit,
    _calculate_maximum_safe_tissue_pressure,
    ambient_pressure_at_depth,
    initialize_tissues,
    load_gas,
)
from master_splinter.processors.dive_analysis import (  # noqa: E402
    analyse_profile,
)
from master_splinter.processors.dive_simulation import (  # noqa: E402
    generate_dive_profile,
)
from master_splinter.theme import (  # noqa: E402
    COMPARTMENT,
    GF_CONSERVATIVE_COLOUR,
    GF_MODERATE_COLOUR,
    MUTED,
    MVALUE_COLOUR,
    SECONDARY_INK,
    SURFACE,
)

DEFAULT_OUTPUT = ROOT / "reports" / "methodology"
STYLE = theme.style_path()

# Colour roles come from palette.py next door. The rationale for each hue,
# and for there being only three compartment slots, lives there.
COMPARTMENT_COLOUR = COMPARTMENT
DETAIL_COLOUR = COMPARTMENT[0]

GF_COLOUR = {
    (0.30, 0.85): GF_CONSERVATIVE_COLOUR,
    (0.50, 0.95): GF_MODERATE_COLOUR,
}
# The line style is not decoration: it is the secondary encoding that makes
# the green/yellow pair legal despite its CVD warning.
LIMIT_STYLE = {(0.30, 0.85): "--", (0.50, 0.95): "-."}

# Fast, medium and slow compartments, 0-based. Compartment 6 (38.3 min)
# is the one the worked example's detail panel follows.
FAST, MEDIUM, SLOW = 0, 7, 15
HIGHLIGHTED = (FAST, MEDIUM, SLOW)
DETAIL = 5

# Gradient factor pairs compared throughout the README.
GF_CONSERVATIVE = (0.30, 0.85)
GF_MODERATE = (0.50, 0.95)
GF_PAIRS = (GF_CONSERVATIVE, GF_MODERATE)

# Depth the gradient factor line is anchored to in the depth-domain figure.
# Without an anchor deeper than the surface the interpolation collapses to
# gf_high everywhere and the figure has nothing to show.
GF_ANCHOR_DEPTH = 30.0

# The worked example from the README's "Simulating a Simple Dive".
# fmt: off
WORKED_EXAMPLE = [
    (15, 1, (0.0, 0.0), "descend"),     # Descend to 15m in 1 min
    (15, 30, (0.0, 0.0), "constant"),   # Stay at 15m for 30 min
    (5, 1, (0.0, 0.0), "ascend"),       # Ascend to 5m in 1 min
    (5, 3, (0.0, 0.0), "constant"),     # Safety stop at 5m for 3 min
    (0, 1, (0.0, 0.0), "ascend"),       # Surface in 1 min
]
# fmt: on

UPTAKE_DEPTH = 15.0
UPTAKE_MINUTES = 120
DEPTH_AXIS = [float(d) for d in range(0, 61)]


def _label(index):
    """Legend label for a compartment, numbered as the README's table is."""
    return f"T{index + 1} ({ZHL16_N2_HALF_TIMES[index]:.1f} min)"


def _gf_label(pair):
    """Legend label for a gradient factor pair."""
    gf_low, gf_high = pair
    return f"GF {gf_low * 100:.0f}/{gf_high * 100:.0f}"


def _legend(axis, **kwargs):
    """Draws a legend on a backing panel.

    The style sheet turns frames off, which is right for a legend over empty
    space and wrong for these figures, where it has to sit over the curves
    it names.

    """
    return axis.legend(
        frameon=True,
        facecolor=SURFACE,
        edgecolor="none",
        framealpha=0.9,
        **kwargs,
    )


def _reference(axis, xs, ys, label):
    """Draws a context line - ambient pressure, an asymptote, an anchor."""
    axis.plot(xs, ys, ":", color=MUTED, linewidth=1.2, label=label, zorder=1)


def _gf_line(index, depths, pair, anchor_depth):
    """GF-adjusted tissue pressure limit across a range of depths."""
    gf_low, gf_high = pair
    anchor_pressure = ambient_pressure_at_depth(anchor_depth)
    return [
        _calculate_gf_limit(
            index,
            ambient_pressure_at_depth(depth),
            gf_low,
            gf_high,
            anchor_pressure,
        )
        for depth in depths
    ]


def figure_tissue_uptake():
    """All 16 compartments loading at a constant depth.

    Sixteen hues would be past the point where categorical colour still
    separates, so the three the rest of the README follows are highlighted
    and the other thirteen recede into a muted ensemble. The spread between
    the fastest and slowest curve is the message; which of the middle
    thirteen is which is not.

    """
    figure, axis = plt.subplots()

    times = list(range(UPTAKE_MINUTES + 1))
    surface = initialize_tissues()
    curves = [
        load_gas(surface, depth=UPTAKE_DEPTH, time=float(minute))
        for minute in times
    ]

    for index in range(len(ZHL16_N2_HALF_TIMES)):
        if index in HIGHLIGHTED:
            continue
        axis.plot(
            times,
            [tissues[index] for tissues in curves],
            color=MUTED,
            linewidth=1,
            alpha=0.45,
            zorder=2,
        )
    # One proxy entry stands in for all thirteen.
    axis.plot(
        [],
        [],
        color=MUTED,
        linewidth=1,
        alpha=0.45,
        label="the other 13 compartments",
    )

    for index in HIGHLIGHTED:
        series = [tissues[index] for tissues in curves]
        axis.plot(
            times,
            series,
            color=COMPARTMENT_COLOUR[index],
            label=_label(index),
            zorder=3,
        )
        # Direct label at the curve's end; the three are far enough apart
        # here for it to be unambiguous, which is not true of every figure.
        axis.annotate(
            _label(index),
            xy=(times[-1], series[-1]),
            xytext=(-6, 6),
            textcoords="offset points",
            ha="right",
            fontsize="small",
            color=SECONDARY_INK,
            # A surface patch behind the text rather than an outline: the
            # ensemble runs underneath these labels at the right edge.
            bbox={
                "facecolor": SURFACE,
                "edgecolor": "none",
                "pad": 1.5,
                "alpha": 0.85,
            },
            zorder=4,
        )

    inspired = curves[-1][FAST]
    _reference(
        axis,
        [times[0], times[-1]],
        [inspired, inspired],
        f"$P_{{inspired}}$ ({inspired:.2f} Bar)",
    )

    axis.set_xlabel("Time (minutes)")
    axis.set_ylabel("Tissue N2 Pressure (Bar)")
    # Below the axes. The curves fan out from a single point at the origin,
    # so any in-plot corner would cover the early minutes of the slow ones.
    _legend(
        axis,
        ncol=3,
        loc="upper center",
        bbox_to_anchor=(0.5, -0.12),
        fontsize="small",
    )
    figure.suptitle(
        f"Simulated Gas Uptake in ZHL-16C Compartments at {UPTAKE_DEPTH:.0f} m"
    )
    figure.tight_layout()
    return figure


def figure_m_values():
    """M-value against depth for a fast, a medium and a slow compartment.

    The lines do not cross. Because b divides the ambient pressure, the
    slope is 1/b: compartment 1's b of 0.5578 gives 1.79 bar per bar, and
    compartment 16's 0.9653 gives 1.04. The fast compartment therefore both
    starts highest and climbs steepest, as the README's A and B table says.

    The retired figure did cross, because it plotted M = a + b * P_ambient
    and so read b as a slope: low b became a shallow line and the ordering
    inverted with depth.

    """
    figure, axis = plt.subplots()

    for index in HIGHLIGHTED:
        axis.plot(
            DEPTH_AXIS,
            [
                _calculate_maximum_safe_tissue_pressure(
                    index, ambient_pressure_at_depth(depth)
                )
                for depth in DEPTH_AXIS
            ],
            color=COMPARTMENT_COLOUR[index],
            label=_label(index),
            zorder=3,
        )

    _reference(
        axis,
        DEPTH_AXIS,
        [ambient_pressure_at_depth(depth) for depth in DEPTH_AXIS],
        "Ambient pressure",
    )

    axis.set_xlabel("Depth (meters)")
    axis.set_ylabel("Max Allowed Tissue Pressure (M-value, Bar)")
    _legend(axis, loc="upper left")
    figure.suptitle("Effect of A and B Values on M-Value Limits")
    figure.tight_layout()
    return figure


def figure_gradient_factors():
    """The raw M-value against two gradient factor lines.

    Both GF lines lie below the M-value at every depth, which is the whole
    mechanism: a gradient factor scales the allowance down towards ambient.
    Deeper than the anchor the factor is clamped to GF_low, which is the
    kink at 30 m.

    """
    figure, axis = plt.subplots()

    axis.plot(
        DEPTH_AXIS,
        [
            _calculate_maximum_safe_tissue_pressure(
                DETAIL, ambient_pressure_at_depth(depth)
            )
            for depth in DEPTH_AXIS
        ],
        color=MVALUE_COLOUR,
        label=f"M-value, {_label(DETAIL)}",
        zorder=3,
    )

    for pair in GF_PAIRS:
        axis.plot(
            DEPTH_AXIS,
            _gf_line(DETAIL, DEPTH_AXIS, pair, GF_ANCHOR_DEPTH),
            LIMIT_STYLE[pair],
            color=GF_COLOUR[pair],
            label=_gf_label(pair),
            zorder=3,
        )

    _reference(
        axis,
        DEPTH_AXIS,
        [ambient_pressure_at_depth(depth) for depth in DEPTH_AXIS],
        "Ambient pressure (GF 0)",
    )

    axis.axvline(
        GF_ANCHOR_DEPTH, color=MUTED, linestyle=":", linewidth=1.2, zorder=1
    )
    axis.annotate(
        f"first stop anchor, {GF_ANCHOR_DEPTH:.0f} m\n"
        "deeper: clamped to GF_low\n"
        "shallower: interpolated to GF_high",
        xy=(GF_ANCHOR_DEPTH + 1.5, 1.2),
        fontsize="small",
        color=SECONDARY_INK,
        va="bottom",
    )

    axis.set_xlabel("Depth (meters)")
    axis.set_ylabel("Max Allowed Tissue Pressure (Bar)")
    _legend(axis, loc="upper left")
    figure.suptitle("Comparison of Gradient Factors (GF) on M-Value Limits")
    figure.tight_layout()
    return figure


def _worked_example_report():
    """The README's worked example, run through the analyser."""
    profile = generate_dive_profile(WORKED_EXAMPLE)
    return analyse_profile(profile, DiveState.at_surface())


def figure_worked_example_profile(report):
    """Depth over time, and one compartment against its limits.

    Two stacked panels sharing a time axis rather than one panel with two
    y-scales: depth and pressure have no common scale, and overlaying them
    would invent a relationship the data does not contain.

    """
    figure, (depth_axis, pressure_axis) = plt.subplots(
        2, 1, sharex=True, figsize=(11, 9)
    )

    times = [sample.time for sample in report.samples]
    depths = [sample.actual_depth for sample in report.samples]
    pressures = [ambient_pressure_at_depth(depth) for depth in depths]
    anchor = report.final_state.anchor

    depth_axis.fill_between(
        times, 0, depths, color=DETAIL_COLOUR, alpha=0.12, zorder=2
    )
    depth_axis.plot(
        times,
        depths,
        color=DETAIL_COLOUR,
        zorder=3,
    )
    depth_axis.invert_yaxis()
    depth_axis.set_ylabel("Depth (meters)")
    # One series, and the panel title names it - a legend box would only
    # sit on top of the final ascent.
    depth_axis.set_title(
        "Dive Profile: 30 min @15 m, ascent to 5 m, 3 min stop, surface"
    )

    pressure_axis.plot(
        times,
        [sample.tissues[DETAIL] for sample in report.samples],
        color=DETAIL_COLOUR,
        label=f"Tissue Pressure, {_label(DETAIL)}",
        zorder=3,
    )
    pressure_axis.plot(
        times,
        [
            _calculate_maximum_safe_tissue_pressure(DETAIL, pressure)
            for pressure in pressures
        ],
        color=MVALUE_COLOUR,
        label="M-value Limit",
        zorder=3,
    )
    for pair in GF_PAIRS:
        pressure_axis.plot(
            times,
            _gf_line(DETAIL, depths, pair, anchor),
            LIMIT_STYLE[pair],
            color=GF_COLOUR[pair],
            label=f"{_gf_label(pair)} Limit",
            zorder=3,
        )

    pressure_axis.set_xlabel("Elapsed Time (minutes)")
    pressure_axis.set_ylabel("Tissue N2 Pressure (Bar)")
    # The band between the tissue curve and the ceilings is empty for the
    # whole bottom phase, which is the only gap big enough for four entries.
    _legend(pressure_axis, loc="center left", fontsize="small")
    pressure_axis.set_title(
        f"Tissue Pressure vs M-Value and GF Limits, {_label(DETAIL)}"
    )

    figure.tight_layout()
    return figure


def figure_worked_example_tissues(report):
    """Fast, medium and slow compartments against their own GF ceilings.

    Each compartment is paired with the ceiling that actually applies to
    it, in the same colour and a dashed line. Drawing one compartment's
    ceiling across all three would compare a pressure against a limit that
    was never its own.

    """
    figure, axis = plt.subplots()

    times = [sample.time for sample in report.samples]
    depths = [sample.actual_depth for sample in report.samples]
    anchor = report.final_state.anchor

    for index in HIGHLIGHTED:
        colour = COMPARTMENT_COLOUR[index]
        axis.plot(
            times,
            [sample.tissues[index] for sample in report.samples],
            color=colour,
            label=_label(index),
            zorder=3,
        )
        axis.plot(
            times,
            _gf_line(index, depths, GF_CONSERVATIVE, anchor),
            "--",
            color=colour,
            linewidth=1.2,
            alpha=0.8,
            label=f"T{index + 1} ceiling",
            zorder=2,
        )

    axis.set_xlabel("Elapsed Time (minutes)")
    axis.set_ylabel("Tissue N2 Pressure (Bar)")
    # Below the axes: the curves and their ceilings between them leave no
    # gap wide enough for a six entry legend.
    _legend(
        axis,
        ncol=3,
        loc="upper center",
        bbox_to_anchor=(0.5, -0.12),
        fontsize="small",
    )
    figure.suptitle(
        f"Tissue Pressures vs Their Own {_gf_label(GF_CONSERVATIVE)} Ceilings"
    )
    figure.tight_layout()
    return figure


def build_figures():
    """Maps output stem to the callable that draws that figure.

    The report is analysed once and shared, so the two worked-example
    figures are guaranteed to depict the same dive.

    """
    report = _worked_example_report()
    return {
        "tissue-uptake": figure_tissue_uptake,
        "m-value-limits": figure_m_values,
        "gradient-factors": figure_gradient_factors,
        "worked-example-profile": lambda: figure_worked_example_profile(
            report
        ),
        "worked-example-tissues": lambda: figure_worked_example_tissues(
            report
        ),
    }


def render(output_dir):
    """Writes every figure, returning the paths written."""
    output_dir.mkdir(parents=True, exist_ok=True)
    plt.style.use(str(STYLE))

    written = []
    for stem, draw in build_figures().items():
        figure = draw()
        path = output_dir / f"{stem}.png"
        figure.savefig(path)
        plt.close(figure)
        written.append(path)
    return written


def main(argv=None):
    """Entry point.

    Returns:
    --------
    status: int
        0 on success.

    """
    parser = argparse.ArgumentParser(
        description=(
            "Regenerate the dark-theme Methodology figures embedded in "
            "README.md."
        )
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"destination directory (default: {DEFAULT_OUTPUT})",
    )
    arguments = parser.parse_args(argv)

    for path in render(arguments.output):
        # An --output outside the repository has no path relative to it.
        print(
            f"wrote {path.relative_to(ROOT) if path.is_relative_to(ROOT) else path}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
