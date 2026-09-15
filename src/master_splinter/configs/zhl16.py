"""Bühlmann ZHL-16C coefficients and the constants of its gas equations.

This module is the algorithm *variant*. Swapping ZHL-16C for 16A is a change to
this file and nothing else; operational limits live in limits.py and the
physical environment in environment.py.

Bühlmann published three coefficient sets. 16A is the original theoretical one,
where both coefficients come straight from the half-time:

    a = 2 / cbrt(halftime)
    b = 1.005 - 1 / sqrt(halftime)

16A proved too permissive against real data, so he replaced the mid and slow
`a` values empirically, giving 16B (for printed tables) and 16C (for dive
computers). The `b` values were never revised and are identical in all three
sets, which is the quickest way to spot a corrupted table.

This implementation uses 16C, the set most dive computers ship.

"""

WATER_VAPOR_PRESSURE = 0.0627  # Bar, at body temperature

# Tissue half-times (minutes) for nitrogen (N2). Shared by all three variants
# except compartment 1: 16A uses 4.0 min, 16B and 16C the 5.0 min "1b"
# compartment, the 4 min one having proved erratic.
# fmt: off
ZHL16_N2_HALF_TIMES = [
    5.0, 8.0, 12.5, 18.5, 27.0, 38.3,
    54.3, 77.0, 109.0, 146.0, 187.0,
    239.0, 305.0, 390.0, 498.0, 635.0
]
# fmt: on

# M-value coefficients A and B for each compartment (air only, not helium).

# ZHL-16C: the dive computer set, and what this module uses.
# fmt: off
ZHL16_A_VALUES = [
    1.1696, 1.0000, 0.8618, 0.7562, 0.6200, 0.5043,
    0.4410, 0.4000, 0.3750, 0.3500, 0.3295,
    0.3065, 0.2835, 0.2610, 0.2480, 0.2327
]
# fmt: on

# fmt: off
ZHL16_B_VALUES = [
    0.5578, 0.6514, 0.7222, 0.7825, 0.8126, 0.8434,
    0.8693, 0.8910, 0.9092, 0.9222, 0.9319,
    0.9403, 0.9477, 0.9544, 0.9602, 0.9653
]
# fmt: on

# ZHL-16A, kept so that changing variant really is the single edit this module
# claims it is. Assign these over the two lists above, and set compartment 1's
# half-time back to 4.0, to get Bühlmann's original theoretical set. Note that
# 16A is markedly more permissive: on a 30 m / 60 min dive it asks for about a
# fifth less decompression than 16C does.
# fmt: off
ZHL16A_A_VALUES = [
    1.2599, 1.0000, 0.8618, 0.7562, 0.6667, 0.5933,
    0.5282, 0.4701, 0.4187, 0.3798, 0.3497,
    0.3223, 0.2971, 0.2737, 0.2523, 0.2327
]

ZHL16A_B_VALUES = [
    0.5050, 0.6514, 0.7222, 0.7825, 0.8126, 0.8434,
    0.8693, 0.8910, 0.9092, 0.9222, 0.9319,
    0.9403, 0.9477, 0.9544, 0.9602, 0.9653
]
# fmt: on
