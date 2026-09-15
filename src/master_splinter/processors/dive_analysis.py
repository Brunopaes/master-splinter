"""Dive profile analysis: execute a planned profile and judge it.

Drives a DiveState through a planned profile, clamping to the decompression
ceiling so the executed dive is one a diver could actually perform, and records
where the plan and the executed dive diverge.

"""

import math
from dataclasses import dataclass, field
from enum import Enum

from master_splinter.configs.environment import SEAWATER_METERS_PER_BAR
from master_splinter.configs.limits import (
    ASCENT_RATE_WINDOW,
    DECO_STEP,
    MAX_ASCENT_RATE,
    PPO2_CONTINGENCY_LIMIT,
    PPO2_WORKING_LIMIT,
)
from master_splinter.model.dive_state import DiveState
from master_splinter.model.splinter_decompression import (
    ambient_pressure_at_depth,
    walk_ceiling_to_surface,
)


class Violation(str, Enum):
    """Ways a planned profile can be unsafe or unexecutable."""

    CEILING = "ceiling_violation"
    ASCENT_RATE = "ascent_rate_exceeded"
    SURFACED_OWING = "surfaced_with_obligation"
    MOD_EXCEEDED = "mod_exceeded"


@dataclass(frozen=True)
class Sample:
    """One time step of the executed dive.

    Attributes:
    -----------
    time: float
        Elapsed minutes.
    planned_depth: float
        Depth the plan called for (meters).
    actual_depth: float
        Depth actually held (meters).
    tissues: tuple
        All 16 tissue nitrogen pressures (Bar), so a renderer can pick any
        compartment without the analysis being re-run.

    """

    time: float
    planned_depth: float
    actual_depth: float
    tissues: tuple[float, ...]


@dataclass(frozen=True)
class Stop:
    """A decompression stop held during the executed dive."""

    depth: float
    duration: float
    started_at: float


@dataclass(frozen=True)
class Finding:
    """A point where the planned profile was unsafe or unexecutable."""

    kind: Violation
    time: float
    depth: float
    detail: str


@dataclass
class DiveReport:
    """The result of analysing a planned profile."""

    samples: list[Sample] = field(default_factory=list)
    stops: list[Stop] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    planned_runtime: float = 0.0
    actual_runtime: float = 0.0
    max_depth: float = 0.0
    final_state: DiveState | None = None

    @property
    def total_deco_time(self):
        """Total minutes spent at decompression stops."""
        return sum(stop.duration for stop in self.stops)

    def findings_of(self, kind: Violation):
        """Returns the findings of one kind."""
        return [f for f in self.findings if f.kind == kind]


def _check_ppo2(
    profile,
    gas_fraction,
    surface_pressure,
    working_limit=PPO2_WORKING_LIMIT,
):
    """Finds the deepest oxygen exposure breach in a planned profile.

    Parameters:
    -----------
    profile: iterable
        Tuples of (depth, duration, elapsed).
    gas_fraction: float
        Nitrogen fraction of the breathing gas.
    surface_pressure: float
        Ambient pressure at the surface (Bar).
    working_limit: float, optional
        ppO2 above which the plan is flagged (Bar, default 1.4). Divers who
        accept more oxygen exposure raise it; conservative or long exposures
        lower it. Must not exceed PPO2_CONTINGENCY_LIMIT - see the note below.

    Returns:
    --------
    findings: list
        At most one Finding, for the deepest breach. Reporting every sample
        would emit hundreds of near-identical rows for one bad plan.

    Notes:
    ------
    ppO2 = oxygen fraction * ambient pressure. The nitrogen model says nothing
    about oxygen toxicity, so without this check a mix can look perfectly safe
    decompression-wise while being unbreathable at depth.

    Two limits, not one: the working limit is what a plan is judged against,
    and the contingency limit is the harder ceiling reserved for
    decompression. A breach is reported against whichever of the two it
    actually crosses, so raising the working limit past the contingency limit
    would make the reported limit go *down* as the breach gets worse. Callers
    must keep working_limit <= PPO2_CONTINGENCY_LIMIT.

    """
    oxygen_fraction = 1.0 - gas_fraction
    if oxygen_fraction <= 0.0:
        return []

    worst = None
    for depth, _, elapsed in profile:
        ambient = ambient_pressure_at_depth(depth, surface_pressure)
        ppo2 = oxygen_fraction * ambient
        if ppo2 > working_limit and (worst is None or ppo2 > worst[0]):
            worst = (ppo2, depth, elapsed)

    if worst is None:
        return []

    ppo2, depth, elapsed = worst
    limit = (
        PPO2_CONTINGENCY_LIMIT
        if ppo2 > PPO2_CONTINGENCY_LIMIT
        else working_limit
    )
    # Inverse of the ppO2 expression above, so the reported MOD is the depth
    # at which the breached limit is exactly reached. Goes through the surface
    # pressure and SEAWATER_METERS_PER_BAR rather than assuming sea level.
    mod = (
        limit / oxygen_fraction - surface_pressure
    ) * SEAWATER_METERS_PER_BAR
    return [
        Finding(
            kind=Violation.MOD_EXCEEDED,
            time=elapsed,
            depth=depth,
            detail=(
                f"ppO2 {ppo2:.2f} bar at {depth:.1f} m exceeds the "
                f"{limit:.1f} bar limit; MOD for this mix is {mod:.1f} m"
            ),
        )
    ]


def _check_ascent_rate(profile, max_rate, window=ASCENT_RATE_WINDOW):
    """Finds the fastest ascent in a planned profile, if it breaches max_rate.

    Parameters:
    -----------
    profile: iterable
        Tuples of (depth, duration, elapsed).
    max_rate: float
        Maximum permitted ascent rate (meters per minute).
    window: float, optional
        Minutes to average the rate over (default ASCENT_RATE_WINDOW).

    Returns:
    --------
    findings: list
        At most one Finding, for the fastest breach.

    Notes:
    ------
    Measured over a window rather than between adjacent samples. A logged
    profile jitters by a metre or two between 10 second samples, and a
    per-sample rate turns that jitter into apparent ascents of 20 m/min while
    the diver is sitting still on the bottom. Dive computers average over a
    comparable window for the same reason.

    """
    worst = None
    trail = []
    for depth, _, elapsed in profile:
        trail.append((elapsed, depth))
        # Keep the oldest sample that is still at least `window` old, so the
        # comparison spans the full window rather than a fraction of it.
        while len(trail) > 1 and elapsed - trail[1][0] >= window:
            trail.pop(0)

        span = elapsed - trail[0][0]
        if span < window:
            continue

        # Tolerance because an ascent planned at exactly the limit lands a
        # few ulps above it, and flagging the recommended rate as a violation
        # trains the reader to ignore the finding.
        rate = (trail[0][1] - depth) / span
        if rate - max_rate > 1e-6 and (worst is None or rate > worst[0]):
            worst = (rate, depth, elapsed)

    if worst is None:
        return []

    rate, depth, elapsed = worst
    return [
        Finding(
            kind=Violation.ASCENT_RATE,
            time=elapsed,
            depth=depth,
            detail=(
                f"ascending at {rate:.1f} m/min, above the "
                f"{max_rate:.1f} m/min limit"
            ),
        )
    ]


def analyse_profile(
    profile,
    state: DiveState | None = None,
    *,
    ascent_rate: float = MAX_ASCENT_RATE,
    deco_step: float = DECO_STEP,
    ppo2_limit: float = PPO2_WORKING_LIMIT,
):
    """Executes a planned dive profile and reports what actually happens.

    Parameters:
    -----------
    profile: iterable
        Tuples of (depth, duration, elapsed) as produced by
        generate_dive_profile or the profile loader.
    state: DiveState or None, optional
        Starting tissue state. A fresh surface state is used when None, so
        residual loading from a previous dive is the caller's business.
    ascent_rate: float, optional
        Rate used for the final ascent and for judging the plan
        (meters per minute).
    deco_step: float, optional
        Time resolution of the decompression walk (minutes).
    ppo2_limit: float, optional
        Working ppO2 limit the plan is judged against (Bar, default 1.4).
        Must not exceed PPO2_CONTINGENCY_LIMIT.

    Returns:
    --------
    report: DiveReport
        Executed samples, stops held, findings, and the final state.

    Notes:
    ------
    Three phases: walk the plan with the ceiling clamped, discharge any
    remaining obligation via the library's own ascent walk, then surface at
    ascent_rate. Phase two consumes walk_ceiling_to_surface directly so the
    executed dive and calculate_deco_schedule cannot disagree.

    """
    profile = list(profile)
    state = state if state is not None else DiveState.at_surface()
    report = DiveReport(final_state=state)

    def record(depth):
        report.samples.append(
            Sample(
                time=state.clock,
                planned_depth=depth[0],
                actual_depth=depth[1],
                tissues=tuple(state.tissues),
            )
        )

    def add_stop(depth, duration):
        # Keyed on depth alone rather than on whether the clamp stayed
        # engaged: a noisy plan dips below the ceiling and back on successive
        # samples, which would otherwise split one stop into fragments.
        if report.stops and report.stops[-1].depth == depth:
            last = report.stops[-1]
            report.stops[-1] = Stop(
                depth=depth,
                duration=last.duration + duration,
                started_at=last.started_at,
            )
        else:
            report.stops.append(
                Stop(depth=depth, duration=duration, started_at=state.clock)
            )

    # Phase 1: follow the plan, never ascending above the ceiling.
    # One finding per contiguous breach, carrying the worst gap in that run,
    # rather than one per sample - a single bad ascent spans hundreds of them.
    breach = None

    def close_breach():
        if breach is None:
            return
        report.findings.append(
            Finding(
                kind=Violation.CEILING,
                time=breach["time"],
                depth=breach["planned"],
                detail=(
                    f"plan calls for {breach['planned']:.1f} m but the "
                    f"ceiling is {breach['ceiling']:.1f} m "
                    f"({breach['gap']:.1f} m above it)"
                ),
            )
        )

    for planned_depth, duration, _ in profile:
        actual_depth = state.clamped_step(planned_depth, duration)
        record((planned_depth, actual_depth))
        report.max_depth = max(report.max_depth, actual_depth)

        if actual_depth > planned_depth:
            add_stop(actual_depth, duration)
            gap = actual_depth - planned_depth
            if breach is None or gap > breach["gap"]:
                breach = {
                    "time": state.clock,
                    "planned": planned_depth,
                    "ceiling": actual_depth,
                    "gap": gap,
                }
        elif breach is not None:
            close_breach()
            breach = None

    close_breach()

    report.planned_runtime = state.clock

    # Phase 2: discharge whatever the plan left owing.
    owed = state.deco_schedule(interval=deco_step)
    if owed and profile and profile[-1][0] <= 0.0:
        report.findings.append(
            Finding(
                kind=Violation.SURFACED_OWING,
                time=state.clock,
                depth=0.0,
                detail=(
                    f"plan surfaces owing {sum(t for _, t in owed):.1f} min, "
                    f"first stop at {owed[0][0]:.1f} m"
                ),
            )
        )

    for ceiling, step_time, tissues, anchor in walk_ceiling_to_surface(
        state.tissues,
        gf_low=state.gf_low,
        gf_high=state.gf_high,
        interval=deco_step,
        gas_fraction=state.gas_fraction,
        surface_pressure=state.surface_pressure,
        anchor=state.anchor,
    ):
        state.tissues = tissues
        state.anchor = anchor
        state.clock += step_time
        record((0.0, ceiling))
        add_stop(ceiling, step_time)

    # Phase 3: surface. Walked out rather than jumped, so a plan that ends
    # deep does not surface in one step with its gas loading applied at 0 m.
    start_depth = report.samples[-1].actual_depth if report.samples else 0.0
    if start_depth > 0.0:
        legs = max(1, math.ceil(start_depth / ascent_rate / deco_step))
        for leg in range(1, legs + 1):
            previous = start_depth * (1.0 - (leg - 1) / legs)
            depth = start_depth * (1.0 - leg / legs)
            # Midpoint: the diver is at neither end of the leg throughout.
            state.step((previous + depth) / 2.0, deco_step)
            report.samples.append(
                Sample(
                    time=state.clock,
                    planned_depth=0.0,
                    actual_depth=depth,
                    tissues=tuple(state.tissues),
                )
            )

    report.actual_runtime = state.clock

    # Judgements about the plan itself, independent of what was executed.
    report.findings.extend(
        _check_ascent_rate(profile, ascent_rate)
        + _check_ppo2(
            profile,
            state.gas_fraction,
            state.surface_pressure,
            working_limit=ppo2_limit,
        )
    )

    return report
