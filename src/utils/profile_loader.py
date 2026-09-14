"""Load dive profiles from dive computer exports.

Produces the same (depth, duration, elapsed) tuples as
dive_simulation.generate_dive_profile, so the analyser does not care whether a
profile was measured or synthesised.

"""

import csv
import json
from pathlib import Path

from configs.limits import MAX_PROFILE_DEPTH


class ProfileFormatError(ValueError):
    """Raised when a dive log cannot be read as a profile."""


def _to_profile(samples):
    """Converts (time, depth) pairs into (depth, duration, elapsed) tuples.

    Parameters:
    -----------
    samples: list of tuples
        (elapsed_minutes, depth_meters), in any order.

    Returns:
    --------
    profile: list of tuples
        Each tuple is (depth, duration, elapsed).

    Raises:
    -------
    ProfileFormatError
        If fewer than two samples are present, a duration is not positive, or
        a depth is negative or implausibly deep.

    Notes:
    ------
    Dive computers log a timestamp and a depth; the model needs the length of
    each step. Duration is the gap to the next sample, and the last sample
    inherits the previous gap since it has no successor.

    Depths are range-checked here rather than left to the model. This is the
    trust boundary: past it a depth is assumed to be a real one, and a figure
    logged in feet or spiked by a failing sensor otherwise travels all the way
    into the ascent walk before anything notices.

    """
    if len(samples) < 2:
        raise ProfileFormatError(
            f"need at least 2 samples to derive step durations, got "
            f"{len(samples)}"
        )

    samples = sorted(samples)
    profile = []
    for index, (elapsed, depth) in enumerate(samples):
        if index + 1 < len(samples):
            duration = samples[index + 1][0] - elapsed
        else:
            duration = profile[-1][1]
        if duration <= 0.0:
            raise ProfileFormatError(
                f"non-increasing timestamps at sample {index} "
                f"(t={elapsed}); durations must be positive"
            )
        if not 0.0 <= depth <= MAX_PROFILE_DEPTH:
            raise ProfileFormatError(
                f"depth {depth} m at sample {index} (t={elapsed}) is outside "
                f"0..{MAX_PROFILE_DEPTH:.0f} m; check the units"
            )
        profile.append((float(depth), float(duration), float(elapsed)))
    return profile


def load_profile(path):
    """Reads a dive profile from a CSV or JSON file.

    Parameters:
    -----------
    path: str or Path
        File to read. Format is chosen by suffix: .json, otherwise CSV.

    Returns:
    --------
    profile: list of tuples
        Each tuple is (depth, duration, elapsed).

    Raises:
    -------
    ProfileFormatError
        If required columns or keys are missing, or values are unparseable.
    FileNotFoundError
        If the path does not exist.

    Notes:
    ------
    CSV expects a header with `time` and `depth` columns (minutes, meters).
    JSON expects either a list of {"time": .., "depth": ..} objects or a
    {"samples": [...]} wrapper.

    """
    path = Path(path)
    text = path.read_text(encoding="utf-8")

    if path.suffix.lower() == ".json":
        return _to_profile(_read_json(text))
    return _to_profile(_read_csv(text))


def _read_json(text):
    """Extracts (time, depth) pairs from JSON text."""
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as error:
        raise ProfileFormatError(f"invalid JSON: {error}") from error

    if isinstance(payload, dict):
        payload = payload.get("samples", [])
    if not isinstance(payload, list):
        raise ProfileFormatError(
            "expected a list of samples or a 'samples' key"
        )

    try:
        return [(float(s["time"]), float(s["depth"])) for s in payload]
    except (KeyError, TypeError, ValueError) as error:
        raise ProfileFormatError(
            f"each sample needs numeric 'time' and 'depth': {error}"
        ) from error


def _read_csv(text):
    """Extracts (time, depth) pairs from CSV text."""
    reader = csv.DictReader(text.splitlines())
    if reader.fieldnames is None:
        raise ProfileFormatError("empty CSV")

    columns = {name.strip().lower(): name for name in reader.fieldnames}
    missing = {"time", "depth"} - columns.keys()
    if missing:
        raise ProfileFormatError(
            f"CSV needs 'time' and 'depth' columns, missing "
            f"{sorted(missing)}; found {reader.fieldnames}"
        )

    try:
        return [
            (float(row[columns["time"]]), float(row[columns["depth"]]))
            for row in reader
        ]
    except (TypeError, ValueError) as error:
        raise ProfileFormatError(
            f"non-numeric time or depth value: {error}"
        ) from error
