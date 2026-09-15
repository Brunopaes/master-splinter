"""The water and the atmosphere the diver moves through.

Physical conversions between depth, elevation and ambient pressure. Neither a
property of the Bühlmann model (see zhl16.py) nor a conservatism choice (see
limits.py).

"""

# Bar, atmospheric pressure at sea level. This is the published International
# Standard Atmosphere reference (101325 Pa), not the rounded 1.0 bar of the
# diving literature, because it is also the P0 the ISA formula below is
# calibrated to. Using 1.0 for both would make every elevation this project
# converts come out ~110 m too high - self-consistent, but a number belonging
# to neither convention.
SURFACE_PRESSURE = 1.01325

# Depth of seawater equivalent to 1 Bar. The conventional 10.0 m figure is used
# rather than the 9.95 m implied by 1025 kg/m³ seawater; the 0.5% difference is
# negligible next to the model's own uncertainty. Change this single
# constant if an exact hydrostatic column is wanted.
SEAWATER_METERS_PER_BAR = 10.0

# International Standard Atmosphere, troposphere layer:
#
#     P(h) = P0 * (1 - LAPSE * h) ** EXPONENT
#
# These two constants fold together the standard temperature lapse rate
# (6.5 K/km), the sea level temperature (288.15 K), gravity and the molar mass
# of air. They are exact as published rather than derived here, which is why
# they are magic numbers rather than a calculation. P0 is SURFACE_PRESSURE

# above: the three are one calibrated set, so rounding P0 while keeping these
# two would not give the standard atmosphere, it would give a curve of the
# right shape through the wrong point.
ISA_LAPSE_COEFFICIENT = 2.25577e-5  # per meter
ISA_EXPONENT = 5.25588  # dimensionless

# The troposphere model holds to roughly 11 km, far above any reachable dive
# site or cabin altitude. Beyond it the formula silently stops being physics,
# so callers reject elevations above this rather than returning a number.
ISA_MAX_ELEVATION = 11000.0  # meters
