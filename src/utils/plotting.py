"""Rendering for dive reports.

Consumes a DiveReport and nothing else. No model calls live here, so the
figure can never disagree with the analysis it depicts.

"""

from pathlib import Path

import matplotlib

# Selected before pyplot is imported, not after. Every consumer of this module
# renders to a file, and choosing the backend at import time means correctness
# does not depend on an importer remembering to call matplotlib.use() first.
matplotlib.use("Agg")

import matplotlib.pyplot as plt

from configs.palette import (
    COMPARTMENT,
    DECO_STOP_COLOUR,
    MUTED,
    PROFILE_INK,
    SURFACE,
)

DEFAULT_STYLE_PATH = (
    Path(__file__).resolve().parents[1] / "configs" / "splinter.mplstyle"
)

# Fast, medium and slow compartments, 0-based.
DEFAULT_COMPARTMENTS = (0, 7, 15)

COMPARTMENT_LABEL = {
    0: "Fast Tissue N2",
    7: "Medium Tissue N2",
    15: "Slow Tissue N2",
}


def _plot_profile(axis, report):
    """Draws the executed dive and, dotted behind it, the plan.

    Depth wears ink rather than a series colour. It is the frame the tissue
    curves are read against - a different quantity on a different axis,
    never compared against them - and the categorical palette has only
    three slots that separate cleanly, which the compartments need.

    """
    times = [sample.time for sample in report.samples]
    axis.plot(
        times,
        [sample.actual_depth for sample in report.samples],
        color=PROFILE_INK,
        label="Dive Profile (executed)",
    )
    axis.plot(
        times,
        [sample.planned_depth for sample in report.samples],
        ":",
        color=MUTED,
        linewidth=1,
        label="Dive Profile (planned)",
    )
    axis.invert_yaxis()  # Depth increases downward
    axis.set_xlabel("Elapsed Time (minutes)")
    axis.set_ylabel("Depth (meters)")
    axis.grid(True)


def _plot_stops(axis, report):
    """Marks the start of each decompression stop."""
    if not report.stops:
        return
    # An event on the profile, not a series: the surface-coloured ring is
    # what separates it from the depth line it sits on, so it does not have
    # to compete with the compartments for a palette slot.
    axis.scatter(
        [stop.started_at for stop in report.stops],
        [stop.depth for stop in report.stops],
        color=DECO_STOP_COLOUR,
        edgecolors=SURFACE,
        linewidths=1.5,
        marker="o",
        s=60,
        zorder=5,
        label="Deco Stop",
    )


def _plot_tissues(axis, report, compartments):
    """Draws selected compartment pressures on a secondary axis."""
    axis.set_ylabel("Tissue N2 Pressure (Bar)")
    times = [sample.time for sample in report.samples]
    for index in compartments:
        axis.plot(
            times,
            [sample.tissues[index] for sample in report.samples],
            "--",
            color=COMPARTMENT.get(index, MUTED),
            label=COMPARTMENT_LABEL.get(index, f"Compartment {index + 1} N2"),
        )


def close_figure(figure):
    """Releases a figure returned by render_dive_report.

    Notes:
    ------
    figure.clf() clears the contents but leaves the figure registered with
    pyplot, which leaks it. Callers should not have to import pyplot just to
    dispose of something this module handed them.

    """
    plt.close(figure)


def render_dive_report(
    report,
    *,
    style_path=DEFAULT_STYLE_PATH,
    output_path=None,
    title="Dive Profile: Depth vs Elapsed Time",
    compartments=DEFAULT_COMPARTMENTS,
):
    """Renders a dive report as a depth and tissue pressure figure.

    Parameters:
    -----------
    report: DiveReport
        The analysed dive.
    style_path: str or Path, optional
        matplotlib style sheet.
    output_path: str or Path or None, optional
        Where to save. Nothing is written when None, which keeps tests off
        the filesystem.
    title: str, optional
        Figure title.
    compartments: tuple, optional
        0-based compartment indices to overlay.

    Returns:
    --------
    figure: matplotlib.figure.Figure
        The rendered figure. The caller owns it and should close it.

    """
    if not report.samples:
        raise ValueError("cannot render a report with no samples")

    plt.style.use(str(style_path))
    figure, depth_axis = plt.subplots(figsize=(10, 5))

    _plot_profile(depth_axis, report)
    _plot_stops(depth_axis, report)

    tissue_axis = depth_axis.twinx()
    _plot_tissues(tissue_axis, report, compartments)

    depth_lines, depth_labels = depth_axis.get_legend_handles_labels()
    tissue_lines, tissue_labels = tissue_axis.get_legend_handles_labels()
    # Drawn on the tissue axis, not the depth one. twinx stacks the overlay
    # above its host, so a legend placed on depth_axis renders underneath
    # the tissue curves and its backing panel hides nothing.
    tissue_axis.legend(
        depth_lines + tissue_lines,
        depth_labels + tissue_labels,
        loc="lower right",
        frameon=True,
        facecolor=SURFACE,
        edgecolor="none",
        framealpha=0.9,
    )

    figure.suptitle(title)
    figure.tight_layout()

    if output_path is not None:
        figure.savefig(output_path)
    return figure
