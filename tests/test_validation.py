"""Tests for the shared bounds checking."""

import pytest

from master_splinter.configs.environment import ISA_MAX_ELEVATION
from master_splinter.configs.limits import PPO2_CONTINGENCY_LIMIT
from master_splinter.validation import (
    elevation,
    gradient_factors,
    ppo2_limit,
)


@pytest.mark.parametrize(
    "text,expected",
    [
        ("30/85", (0.30, 0.85)),
        ("50/95", (0.50, 0.95)),
        ("100/100", (1.0, 1.0)),
        ("85/85", (0.85, 0.85)),
    ],
)
def test_gradient_factors_parses_a_pair(text, expected):
    assert gradient_factors(text) == pytest.approx(expected)


@pytest.mark.parametrize(
    "text",
    [
        "30",  # no separator
        "30/85/95",  # too many parts
        "low/high",  # not numbers
        "30.5/85",  # not integers
        "",
        "0/85",  # low must exceed zero
        "85/30",  # inverted
        "30/101",  # above 100
        "-10/85",
    ],
)
def test_gradient_factors_rejects(text):
    with pytest.raises(ValueError):
        gradient_factors(text)


@pytest.mark.parametrize("text,expected", [("1.4", 1.4), ("1.6", 1.6)])
def test_ppo2_limit_parses(text, expected):
    assert ppo2_limit(text) == pytest.approx(expected)


def test_ppo2_limit_allows_exactly_the_contingency_limit():
    assert ppo2_limit(str(PPO2_CONTINGENCY_LIMIT)) == pytest.approx(
        PPO2_CONTINGENCY_LIMIT
    )


@pytest.mark.parametrize("text", ["0", "-1.4", "1.7", "lots", ""])
def test_ppo2_limit_rejects(text):
    with pytest.raises(ValueError):
        ppo2_limit(text)


@pytest.mark.parametrize("text,expected", [("2400", 2400.0), ("0", 0.0)])
def test_elevation_parses(text, expected):
    assert elevation(text) == pytest.approx(expected)


def test_elevation_allows_descent():
    """Descending raises ambient pressure and is always safe."""
    assert elevation("-500") == pytest.approx(-500.0)


@pytest.mark.parametrize("meters", [ISA_MAX_ELEVATION, -ISA_MAX_ELEVATION])
def test_elevation_allows_the_troposphere_bound(meters):
    assert elevation(str(meters)) == pytest.approx(meters)


@pytest.mark.parametrize(
    "text",
    [
        "11001",  # past where the ISA formula is physics
        "-11001",
        "nan",
        "inf",
        "-inf",
        "high",
        "",
    ],
)
def test_elevation_rejects(text):
    with pytest.raises(ValueError):
        elevation(text)
