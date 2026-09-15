"""Elevation and ambient pressure.

The decompression model is written in ambient pressure; depth and elevation are
two ways of naming a pressure. Depth is handled in splinter_decompression
(pressure rises below the surface); this module handles the other direction
(pressure falls above it), so a diver driving over a pass or boarding an
aircraft can be analysed with the same equations as a diver surfacing.

"""

from master_splinter.configs.environment import (
    ISA_EXPONENT,
    ISA_LAPSE_COEFFICIENT,
    ISA_MAX_ELEVATION,
    SURFACE_PRESSURE,
)


def pressure_at_elevation(
    elevation: float,
    sea_level_pressure: float = SURFACE_PRESSURE,
):
    """Ambient pressure at an elevation above sea level.

    Parameters:
    -----------
    elevation: float
        Meters above sea level. Negative values (below sea level, such as the
        Dead Sea) are allowed and give a pressure above sea level pressure.
    sea_level_pressure: float, optional
        Ambient pressure at sea level (Bar, default 1.01325).

    Returns:
    --------
    pressure: float
        Ambient pressure at that elevation (Bar).

    Raises:
    -------
    ValueError
        If the elevation is outside the range the troposphere model covers.

    Notes:
    ------
    International Standard Atmosphere, troposphere layer:

        P(h) = P0 * (1 - 2.25577e-5 * h) ** 5.25588

    """
    if elevation > ISA_MAX_ELEVATION:
        raise ValueError(
            f"elevation {elevation:.0f} m is above the {ISA_MAX_ELEVATION:.0f}"
            " m ceiling of the troposphere model"
        )
    base = 1.0 - ISA_LAPSE_COEFFICIENT * elevation
    if base <= 0.0:
        raise ValueError(f"elevation {elevation:.0f} m is not physical")
    return sea_level_pressure * base**ISA_EXPONENT


def elevation_at_pressure(
    pressure: float,
    sea_level_pressure: float = SURFACE_PRESSURE,
):
    """Elevation at which ambient pressure takes a given value.

    Parameters:
    -----------
    pressure: float
        Ambient pressure (Bar). Must be positive.
    sea_level_pressure: float, optional
        Ambient pressure at sea level (Bar, default 1.01325).

    Returns:
    --------
    elevation: float
        Meters above sea level. Negative when the pressure is above sea level
        pressure.

    Raises:
    -------
    ValueError
        If the pressure is not positive.

    Notes:
    ------
    Exact inverse of pressure_at_elevation, so the pair round-trips.

    """
    if pressure <= 0.0:
        raise ValueError(f"pressure must be positive, got {pressure}")
    ratio = (pressure / sea_level_pressure) ** (1.0 / ISA_EXPONENT)
    return (1.0 - ratio) / ISA_LAPSE_COEFFICIENT
