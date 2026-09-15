"""Persist tissue loading between dives.

What carries over from one dive to the next is the tissue nitrogen pressures,
not the M-values: M-values are `P_ambient / b + a`, derived from fixed ZHL-16C
coefficients, and are identical on every dive. The pressures are what a
repetitive dive has to account for.

Reading a state file and ageing it are deliberately separate. Dive analysis
wants both at once; altitude analysis wants the file as saved and ages it
against its own surface interval. Conflating the two forces every caller into
the dive-analysis assumptions.

Every entry point takes an explicit path. There is no default location: where
a caller keeps its state is the caller's decision, and a library that picked
one would be writing next to its own installed source.

"""

import json
import math
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from master_splinter.configs.environment import SURFACE_PRESSURE
from master_splinter.configs.limits import N2_FRACTION_AIR
from master_splinter.model.splinter_decompression import load_gas

# Bumped to 2 when SURFACE_PRESSURE moved from a rounded 1.0 bar to the ISA
# sea level reference. A version 1 file records a sea level dive as 1.0 bar,
# which under the current reference is an elevation of ~110 m - so the file is
# not merely stale, it silently describes a different dive site. Rejecting it
# degrades to "start fresh", which is the safe reading.
SCHEMA_VERSION = 2


@dataclass(frozen=True)
class SavedState:
    """Tissue loading as recorded at the end of a dive.

    Attributes:
    -----------
    tissues: list
        The 16 tissue nitrogen pressures (Bar).
    saved_at: datetime or None
        When the state was written, timezone-aware. None when the file carried
        no usable timestamp, in which case no wall-clock interval can be
        derived.
    surface_pressure: float
        Ambient pressure at the surface the dive was made at (Bar). Carried so
        a dive at altitude resumes at the pressure it was logged at.
    gas_fraction: float
        Nitrogen fraction of the *dive* gas. Recorded for reporting only -
        never use it to off-gas at the surface, where the diver breathes air.

    """

    tissues: list[float]
    saved_at: datetime | None
    surface_pressure: float
    gas_fraction: float

    def minutes_since(self, now=None):
        """Wall-clock minutes at the surface since this state was saved.

        Parameters:
        -----------
        now: datetime or None, optional
            Current time. Defaults to the current UTC time.

        Returns:
        --------
        minutes: float
            Zero when the file carried no usable timestamp, and clamped at
            zero when the clock has gone backwards - see _elapsed_minutes.

        """
        return _elapsed_minutes(self.saved_at, now)


def _number(value, default):
    """Coerces a payload field to float, falling back on anything unusable.

    Notes:
    ------
    `payload.get(key, default)` is not enough: a key present but null returns
    None, which then fails deep inside the model with a TypeError. A corrupt
    state file must degrade, never abort.

    """
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    # NaN and infinity survive float() and would poison every downstream
    # pressure calculation silently.
    if not math.isfinite(number):
        return default
    return number


def save_tissues(state, path, *, now=None):
    """Writes tissue pressures and a timestamp for the next dive to pick up.

    Parameters:
    -----------
    state: DiveState
        State whose tissues are recorded.
    path: str or Path
        Destination file.
    now: datetime or None, optional
        Timestamp to record. Defaults to the current UTC time.

    Notes:
    ------
    The gradient factor anchor is deliberately not saved. A new dive starts
    with a fresh gradient factor line; carrying the previous dive's anchor
    would wrongly loosen its first stop.

    The write is atomic: a temporary file in the same directory, flushed and
    fsynced, then os.replace over the destination. Writing in place would
    truncate first, so losing power mid-write - which a battery-powered dive
    computer does - leaves a half-written file. read_state cannot parse that,
    returns None, and a caller following the documented "degrade to start
    fresh" contract would then model a loaded diver as clean. A reader here
    sees either the previous state or the new one, never a torn one.

    """
    path = Path(path)
    stamp = now if now is not None else datetime.now(UTC)
    payload = {
        "version": SCHEMA_VERSION,
        "saved_at": stamp.isoformat(),
        "surface_pressure": state.surface_pressure,
        "gas_fraction": state.gas_fraction,
        "tissues": list(state.tissues),
    }
    # Same directory, so the replace below is a rename within one filesystem.
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    try:
        with temporary.open("w", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, indent=2) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def _read_payload(path):
    """Reads a state file, reporting why when it cannot be used.

    Returns:
    --------
    result: tuple
        (SavedState, None) when the file is usable, otherwise (None, reason).
        `reason` is None for a file that simply is not there, which is not a
        problem - a first dive is planned from nothing. It is a string only
        when a file exists and cannot be used, which a caller should tell the
        diver about rather than quietly starting them fresh.

    """
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None, None
    except OSError as error:
        return None, f"cannot be read ({error.strerror})"

    try:
        payload = json.loads(text)
    except json.JSONDecodeError as error:
        return None, f"is not valid JSON ({error})"

    if not isinstance(payload, dict):
        return None, "is not a JSON object"

    version = payload.get("version")
    if version != SCHEMA_VERSION:
        return None, (
            f"has schema version {version!r}, expected {SCHEMA_VERSION}"
        )

    tissues = payload.get("tissues")
    if not isinstance(tissues, list) or len(tissues) != 16:
        return None, "does not hold a list of 16 tissue pressures"
    try:
        tissues = [float(pressure) for pressure in tissues]
    except (TypeError, ValueError):
        return None, "has a non-numeric tissue pressure"

    return (
        SavedState(
            tissues=tissues,
            saved_at=_parse_stamp(payload.get("saved_at")),
            surface_pressure=_number(
                payload.get("surface_pressure"), SURFACE_PRESSURE
            ),
            gas_fraction=_number(payload.get("gas_fraction"), N2_FRACTION_AIR),
        ),
        None,
    )


def read_state(path):
    """Reads a state file exactly as saved, without ageing it.

    Parameters:
    -----------
    path: str or Path
        File to read.

    Returns:
    --------
    state: SavedState or None
        None when there is no usable saved state.

    Notes:
    ------
    Any unreadable file returns None rather than raising. A corrupt state file
    should degrade to "start fresh", never abort an analysis - but see
    state_problem. Degrading quietly and degrading invisibly are different
    things, and a caller that starts a diver fresh should say so.

    """
    return _read_payload(path)[0]


def state_problem(path):
    """Why a state file cannot be used, for reporting to the diver.

    Parameters:
    -----------
    path: str or Path
        File to check.

    Returns:
    --------
    reason: str or None
        A phrase completing "the state file <reason>", or None when the file
        is usable or simply absent.

    Notes:
    ------
    Falling back to surface equilibrium understates the obligation of a diver
    who really is loaded, so the fallback has to be visible. Absence is not
    reported: planning a first dive from nothing is the normal case, not a
    degraded one.

    """
    return _read_payload(path)[1]


def age_tissues(tissues, minutes, surface_pressure=SURFACE_PRESSURE):
    """Off-gasses tissues for time spent at the surface.

    Parameters:
    -----------
    tissues: list
        Tissue nitrogen pressures (Bar).
    minutes: float
        Time at the surface. Values at or below zero return the input
        unchanged.
    surface_pressure: float, optional
        Ambient pressure at the surface (Bar).

    Returns:
    --------
    tissues: list
        Updated tissue nitrogen pressures.

    Notes:
    ------
    The gas is air, always. A diver breathes air at the surface whatever they
    dived on, so the saved `gas_fraction` must not be used here - it would
    off-gas an EAN40 diver as if they were still on their nitrox.

    """
    if minutes <= 0.0:
        return list(tissues)
    return load_gas(
        tissues,
        depth=0.0,
        time=minutes,
        gas_fraction=N2_FRACTION_AIR,
        surface_pressure=surface_pressure,
    )


def load_state(
    path,
    *,
    now=None,
    surface_interval=None,
):
    """Reads a state file and off-gasses it for the surface time.

    Parameters:
    -----------
    path: str or Path
        File to read.
    now: datetime or None, optional
        Current time, used to derive the surface interval. Defaults to the
        current UTC time.
    surface_interval: float or None, optional
        Minutes spent at the surface. Overrides the wall clock, which is what
        you want for planning a repetitive dive that has not happened yet.

    Returns:
    --------
    result: tuple or None
        (SavedState with aged tissues, surface_interval_minutes), or None when
        there is no usable saved state.

    Notes:
    ------
    The returned state keeps the saved surface pressure, so a caller can build
    a DiveState that resumes at the altitude the dive was logged at rather than
    silently reverting to sea level.

    """
    saved = read_state(path)
    if saved is None:
        return None

    if surface_interval is None:
        surface_interval = _elapsed_minutes(saved.saved_at, now)
    surface_interval = max(0.0, _number(surface_interval, 0.0))

    aged = age_tissues(saved.tissues, surface_interval, saved.surface_pressure)
    return (
        SavedState(
            tissues=aged,
            saved_at=saved.saved_at,
            surface_pressure=saved.surface_pressure,
            gas_fraction=saved.gas_fraction,
        ),
        surface_interval,
    )


def load_tissues(path, *, now=None, surface_interval=None):
    """Convenience wrapper over load_state for callers wanting only tissues.

    Returns:
    --------
    result: tuple or None
        (tissues, surface_interval_minutes), or None.

    """
    result = load_state(path, now=now, surface_interval=surface_interval)
    if result is None:
        return None
    saved, interval = result
    return saved.tissues, interval


def _parse_stamp(saved_at):
    """Parses a stored ISO timestamp into an aware datetime, or None."""
    if not isinstance(saved_at, str):
        return None
    try:
        stamp = datetime.fromisoformat(saved_at)
    except ValueError:
        return None
    return stamp.replace(tzinfo=UTC) if stamp.tzinfo is None else stamp


def _elapsed_minutes(saved_at, now):
    """Minutes between a stored timestamp and now, clamped at zero.

    Notes:
    ------
    Clamped because a clock that has gone backwards - skew, a timezone edit,
    a hand-written state file - would otherwise ongas the diver at the
    surface, which is worse than simply crediting no surface time.

    """
    if saved_at is None:
        return 0.0

    current = now if now is not None else datetime.now(UTC)
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    return max(0.0, (current - saved_at).total_seconds() / 60.0)
