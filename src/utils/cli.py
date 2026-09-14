"""Shared argparse types for the handlers.

Validation lives here rather than in one handler so a second command cannot
drift from the first on what counts as a legal gradient factor pair or ppO2
limit. Each raises argparse.ArgumentTypeError, so argparse reports the problem
and exits 2 before any analysis runs.

"""

import argparse
import math

from configs.environment import ISA_MAX_ELEVATION
from configs.limits import PPO2_CONTINGENCY_LIMIT


def gradient_factors(text):
    """Parses a LOW/HIGH gradient factor pair such as '30/85'."""
    try:
        low, high = (int(part) for part in text.split("/"))
    except ValueError as error:
        raise argparse.ArgumentTypeError(
            f"expected LOW/HIGH such as 30/85, got {text!r}"
        ) from error
    if not 0 < low <= high <= 100:
        raise argparse.ArgumentTypeError(
            f"need 0 < low <= high <= 100, got {low}/{high}"
        )
    return low / 100.0, high / 100.0


def ppo2_limit(text):
    """Parses the working ppO2 limit in bar, capped at the contingency limit.

    Notes:
    ------
    The cap is the contingency limit rather than an arbitrary ceiling: the
    analyser reports a breach against whichever of the two limits it crosses,
    so a working limit above the contingency limit would make the reported
    limit fall as the breach worsens. 1.6 bar is also the accepted hard
    ceiling for oxygen exposure, so there is no dive that wants more.

    """
    try:
        limit = float(text)
    except ValueError as error:
        raise argparse.ArgumentTypeError(
            f"expected a ppO2 in bar such as 1.4, got {text!r}"
        ) from error
    if not 0.0 < limit <= PPO2_CONTINGENCY_LIMIT:
        raise argparse.ArgumentTypeError(
            f"need 0 < limit <= {PPO2_CONTINGENCY_LIMIT}, got {limit}"
        )
    return limit


def elevation(text):
    """Parses a signed elevation change in meters.

    Notes:
    ------
    Negative is allowed and meaningful - descending raises ambient pressure and
    is always safe. The bound is where the troposphere formula stops being
    physics, not a judgement about what a diver might attempt.

    """
    try:
        meters = float(text)
    except ValueError as error:
        raise argparse.ArgumentTypeError(
            f"expected a signed elevation in meters, got {text!r}"
        ) from error
    if not math.isfinite(meters):
        raise argparse.ArgumentTypeError(
            f"expected a finite elevation in meters, got {text!r}"
        )
    if abs(meters) > ISA_MAX_ELEVATION:
        raise argparse.ArgumentTypeError(
            f"need |elevation| <= {ISA_MAX_ELEVATION:.0f} m, got {meters}"
        )
    return meters
