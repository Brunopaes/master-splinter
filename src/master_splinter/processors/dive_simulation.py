"""Dive Profile Simulation Module."""

import random


def generate_dive_profile(dive_boundaries, interval: float = 1.0 / 6.0):
    """Generates a fluctuating dive profile based on bounds and phases.

    Parameters:
    -----------
    dive_boundaries: list of tuples
        Each tuple is (target_depth, duration_minutes, (min_var, max_var),
        phase), where phase is one of 'descend', 'constant' or 'ascend'.
    interval: float
        Time step in minutes (default ~10 seconds)

    Returns:
    --------
    profile: list of tuples
        Each tuple is (depth, interval, elapsed_time)

    Notes:
    ------
    Each sample records the depth at the *end* of its time step, so a ramp
    segment lands exactly on target_depth on its final step and consecutive
    segments join without a depth discontinuity.

    """
    profile: list = []
    prev_depth = 0.0
    total_steps = 0
    for target_depth, duration, var_range, phase in dive_boundaries:
        # round() rather than int(): int() truncates, so a duration that is not
        # an exact multiple of interval loses up to a full step per segment.
        steps = max(1, round(duration / interval))
        for step in range(steps):
            if phase in ("descend", "ascend"):
                # (step + 1) / steps reaches 1.0 on the final step, so the
                # segment actually arrives at target_depth.
                base_depth = prev_depth + (target_depth - prev_depth) * (
                    (step + 1) / steps
                )
            else:
                base_depth = target_depth

            # Ensure depth is non-negative
            depth = max(0, base_depth + random.uniform(*var_range))
            # Derive elapsed from a step count rather than accumulating floats,
            # which drifts over a few hundred steps.
            profile.append((float(depth), interval, total_steps * interval))
            total_steps += 1

        prev_depth = target_depth
    return profile
