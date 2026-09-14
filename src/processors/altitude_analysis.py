"""Altitude exposure after a dive.

Going to altitude lowers ambient pressure, which is arithmetically the same
thing as surfacing further: residual nitrogen that was tolerable at the dive
site can be supersaturated at the top of a mountain pass or in an aircraft
cabin. This module answers the question a diver actually asks - can I make this
elevation change now, and if not, how long must I wait.

The decompression model is untouched by any of this. All that is needed is to
express the target elevation as an ambient pressure and ask the tissues whether
they tolerate it.

"""

from dataclasses import dataclass

from configs.environment import SURFACE_PRESSURE
from configs.zhl16 import ZHL16_N2_HALF_TIMES
from model.atmosphere import elevation_at_pressure, pressure_at_elevation
from model.splinter_decompression import (
    limiting_compartment,
    tolerated_ambient_pressure,
)
from utils.state_store import age_tissues

# Longest surface interval the wait search will consider. A fully rested diver
# at sea level still cannot tolerate an unlimited elevation gain - at
# equilibrium the slowest compartment tops out around 5,600 m under raw
# Bühlmann - so some gains are unreachable at any interval and the search has
# to be allowed to give up rather than run forever.
_MAX_WAIT_MINUTES = 60.0 * 24.0 * 7.0

# Resolution of the bisection, in minutes. Finer than any diver would act on.
_WAIT_RESOLUTION = 0.1


@dataclass(frozen=True)
class Verdict:
    """Whether one conservatism setting permits the elevation change.

    Attributes:
    -----------
    label: str
        Human name for the conservatism used, e.g. 'raw Bühlmann' or 'GF 85'.
    gf: float
        Gradient factor applied (1.0 is raw Bühlmann).
    safe: bool
        True when the target pressure is tolerated right now.
    tolerated_pressure: float
        Lowest ambient pressure the tissues tolerate (Bar).
    limiting_compartment: int
        1-based index of the compartment setting that limit, as a diver would
        number it.
    limiting_half_time: float
        Half-time of that compartment (minutes).
    margin: float
        target_pressure - tolerated_pressure (Bar). Negative is a breach.
    wait_minutes: float or None
        Additional surface time needed before the change is safe. 0.0 when
        already safe, None when no surface interval makes it safe.
    max_gain: float
        Largest elevation gain tolerable right now (meters). Negative means
        even staying put is outside the limit.

    """

    label: str
    gf: float
    safe: bool
    tolerated_pressure: float
    limiting_compartment: int
    limiting_half_time: float
    margin: float
    wait_minutes: float | None
    max_gain: float


@dataclass(frozen=True)
class AltitudeReport:
    """The result of analysing an elevation change after a dive."""

    elevation_gain: float
    surface_interval: float
    start_elevation: float
    start_pressure: float
    target_pressure: float
    raw: Verdict
    gradient: Verdict

    @property
    def safe(self):
        """True only when both conservatism settings permit the change."""
        return self.raw.safe and self.gradient.safe


def _wait_for(tissues, target_pressure, gf, surface_pressure):
    """Minimum extra surface minutes until target_pressure is tolerated.

    Notes:
    ------
    Bisection is valid because holding at the surface drives every compartment
    toward the inspired pressure there, so the tolerated pressure decreases
    monotonically with time. The feasibility check first: some gains are
    unreachable however long the diver waits.

    """
    if tolerated_ambient_pressure(tissues, gf) <= target_pressure:
        return 0.0

    def tolerated_after(minutes):
        return tolerated_ambient_pressure(
            age_tissues(tissues, minutes, surface_pressure), gf
        )

    if tolerated_after(_MAX_WAIT_MINUTES) > target_pressure:
        return None

    low, high = 0.0, _MAX_WAIT_MINUTES
    while high - low > _WAIT_RESOLUTION:
        middle = (low + high) / 2.0
        if tolerated_after(middle) <= target_pressure:
            high = middle
        else:
            low = middle
    return high


def _verdict(
    label, gf, tissues, target_pressure, start_elevation, surface_pressure
):
    """Builds one Verdict for a single conservatism setting."""
    tolerated = tolerated_ambient_pressure(tissues, gf)
    index = limiting_compartment(tissues, gf)
    # The shallowest pressure tolerated maps to the highest elevation
    # tolerated; anything above that is the gain the diver cannot yet make.
    max_elevation = elevation_at_pressure(tolerated)

    return Verdict(
        label=label,
        gf=gf,
        safe=target_pressure >= tolerated,
        tolerated_pressure=tolerated,
        limiting_compartment=index + 1,
        limiting_half_time=ZHL16_N2_HALF_TIMES[index],
        margin=target_pressure - tolerated,
        wait_minutes=_wait_for(tissues, target_pressure, gf, surface_pressure),
        max_gain=max_elevation - start_elevation,
    )


def analyse_altitude_change(
    tissues,
    elevation_gain: float,
    *,
    surface_interval: float = 0.0,
    gf_high: float = 0.85,
    surface_pressure: float = SURFACE_PRESSURE,
):
    """Decides whether an elevation change is safe on a given surface interval.

    Parameters:
    -----------
    tissues: list
        Tissue nitrogen pressures as saved at the end of the dive (Bar). Not
        yet aged - this function applies the surface interval itself.
    elevation_gain: float
        Meters to ascend, relative to the dive site. Negative is a descent and
        is always safe.
    surface_interval: float, optional
        Minutes already spent at the surface before the change (default 0).
    gf_high: float, optional
        Gradient factor applied at the surface (default 0.85). There is no
        ascent to interpolate along here, so gf_low plays no part.
    surface_pressure: float, optional
        Ambient pressure at the dive site (Bar, default 1.01325).

    Returns:
    --------
    report: AltitudeReport
        Verdicts under raw Bühlmann and under the gradient factor.

    Notes:
    ------
    Off-gassing at the surface is on air whatever the dive gas was; that is
    age_tissues' business and this function does not override it.

    No gradient factor anchor is involved. The anchor exists to interpolate
    along an ascent between the first stop and the surface, and a diver sitting
    on the beach is not on an ascent. gf_high is the surfacing factor and is
    the right one to apply to a further pressure reduction.

    """
    aged = age_tissues(tissues, surface_interval, surface_pressure)

    start_elevation = elevation_at_pressure(surface_pressure)
    target_pressure = pressure_at_elevation(start_elevation + elevation_gain)

    return AltitudeReport(
        elevation_gain=elevation_gain,
        surface_interval=surface_interval,
        start_elevation=start_elevation,
        start_pressure=surface_pressure,
        target_pressure=target_pressure,
        raw=_verdict(
            "raw Bühlmann",
            1.0,
            aged,
            target_pressure,
            start_elevation,
            surface_pressure,
        ),
        gradient=_verdict(
            f"GF {gf_high * 100:.0f}",
            gf_high,
            aged,
            target_pressure,
            start_elevation,
            surface_pressure,
        ),
    )
