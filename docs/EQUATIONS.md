# Equations of the `Bühlmann-Splinter` Model

Every equation the implementation actually evaluates, in one place, written
the way `src/model/splinter_decompression.py` writes it. Each is rendered by
GitHub's own `LaTeX` support rather than as an image, so the glyphs inherit
the page's text colour and follow whichever theme the reader has set.

> **Convention:** lowercase $a$ and $b$ are the per-compartment `ZHL-16C`
> coefficients from `src/configs/zhl16.py`. All pressures are absolute, in
> bar, against the `ISA` sea level $P_0 = 1.01325$ bar described under
> [The Sea Level Reference](../README.md#the-sea-level-reference).

> **Editing note.** Keep `$$` blocks out of `<details>`. `GitHub` renders
> only the _first_ such block in a document and leaves every later one as
> literal `$$`, which is why the `README` shows each equation above its
> collapsed symbol list rather than inside it.

## Contents

- [1. Surface Equilibrium](#1-surface-equilibrium)
- [2. Ambient Pressure](#2-ambient-pressure)
- [3. Inspired Inert Gas Pressure](#3-inspired-inert-gas-pressure)
- [4. Tissue Gas Uptake and Elimination](#4-tissue-gas-uptake-and-elimination)
- [5. `M-Value`](#5-m-value)
- [6. Ascent Ceiling](#6-ascent-ceiling)
- [7. Gradient Factors](#7-gradient-factors)
- [8. Elevation](#8-elevation)

## 1. Surface Equilibrium

Where every dive starts. Tissues sit in equilibrium with the _alveolar_
nitrogen pressure, so the water vapour of the lungs comes off the surface
pressure before the gas fraction is applied:

$$
\large P_{\text{tissue}}(0) = f_{N_2} \cdot \left( P_{\text{surface}} - P_{H_2O} \right)
$$

| Symbol | Meaning | Value |
| ------ | ------- | ----- |
| $f_{N_2}$ | nitrogen fraction of air | `0.79` — `N2_FRACTION_AIR` |
| $P_{\text{surface}}$ | ambient pressure at the surface | `1.01325 bar` — `SURFACE_PRESSURE` |
| $P_{H_2O}$ | water vapour pressure in the lungs | `0.0627 bar` — `WATER_VAPOR_PRESSURE` |

At sea level this is `0.7509 bar`. Texts quoting `0.7405 bar` are evaluating
the same expression at a rounded `1.0 bar` surface.

> Implemented by `initialize_tissues`.

## 2. Ambient Pressure

$$
\large P_{\text{ambient}} = P_{\text{surface}} + \frac{d}{10}
$$

| Symbol | Meaning |
| ------ | ------- |
| $d$ | depth below the surface, in meters |
| $10$ | meters of seawater per bar — `SEAWATER_METERS_PER_BAR` |

> Implemented by `ambient_pressure_at_depth`.

## 3. Inspired Inert Gas Pressure

$$
\large P_{\text{inspired}} = f_{\text{gas}} \cdot \left( P_{\text{ambient}} - P_{H_2O} \right)
$$

| Symbol | Meaning |
| ------ | ------- |
| $f_{\text{gas}}$ | inert gas fraction of the breathing mix — `GAS_MIXES` |
| $P_{\text{ambient}}$ | ambient pressure at the current depth |

> Implemented inside `load_gas_at_pressure`.

## 4. Tissue Gas Uptake and Elimination

Each compartment is a first-order exponential approach to the inspired
pressure:

$$
\large P_{\text{tissue}}(t) = P_{\text{tissue}}(0) + \left( P_{\text{inspired}} - P_{\text{tissue}}(0) \right) \left( 1 - e^{-kt} \right)
$$

with the rate constant set by the compartment's half-time:

$$
\large k = \frac{\ln 2}{t_{1/2}}
$$

| Symbol | Meaning |
| ------ | ------- |
| $P_{\text{tissue}}(t)$ | inert gas pressure in the tissue after time $t$ |
| $P_{\text{tissue}}(0)$ | tissue pressure at the start of the step |
| $t$ | time at that pressure, in minutes |
| $t_{1/2}$ | compartment half-time, in minutes — `ZHL16_N2_HALF_TIMES` |

One equation serves both directions: **on-gassing** when
$P_{\text{inspired}} > P_{\text{tissue}}$, **off-gassing** when it is lower.

> Implemented by `load_gas_at_pressure`.

## 5. `M-Value`

The maximum inert gas pressure a compartment tolerates at a given ambient
pressure:

$$
\large M = \frac{P_{\text{ambient}}}{b} + a
$$

| Symbol | Meaning |
| ------ | ------- |
| $a$ | compartment intercept — `ZHL16_A_VALUES` |
| $b$ | compartment reciprocal slope — `ZHL16_B_VALUES` |
| $M$ | maximum safe tissue pressure at that ambient pressure |

> $b$ **divides** the ambient pressure; it does not multiply it. A _lower_
> $b$ therefore makes the `M-value` climb _faster_ with depth. At sea level
> compartment 1 gives `2.99 bar`; the `2.96 bar` of the published table is
> the same expression at a rounded `1.0 bar` surface.

If $P_{\text{tissue}} > M$, a decompression stop is required.

> Implemented by `_calculate_maximum_safe_tissue_pressure`.

## 6. Ascent Ceiling

Rearranging §5 for the shallowest ambient pressure the compartment tolerates
right now:

$$
\large P_{\text{ambient}}^{\min} = \left( P_{\text{tissue}} - a \right) \cdot b
$$

Converted back to a depth below the surface:

$$
\large \text{ceiling} = \max\left( 0,\; \left( P_{\text{ambient}}^{\min} - P_{\text{surface}} \right) \cdot 10 \right)
$$

The diver is held by whichever compartment tolerates the _least_, so the
governing ceiling is the **maximum** of $P_{\text{ambient}}^{\min}$ across
all 16.

> Implemented by `_calculate_minimum_ambient_pressure`, aggregated by
> `tolerated_ambient_pressure` and converted by `calculate_ceiling`.

## 7. Gradient Factors

### The limit

A gradient factor scales the allowance down from the full `M-value` towards
ambient pressure:

$$
\large P_{\text{allowed}} = P_{\text{ambient}} + GF \cdot \left( M - P_{\text{ambient}} \right)
$$

$GF = 1$ is raw `Bühlmann`; $GF = 0$ would permit no supersaturation at all.
Because $0 \le GF \le 1$, the limit always lies **between** ambient pressure
and the `M-value`, never above it.

### The interpolation

$GF$ is not one number. It runs from $GF_{\text{low}}$ at the first stop to
$GF_{\text{high}}$ at the surface:

$$
\large GF = GF_{\text{high}} - \left( GF_{\text{high}} - GF_{\text{low}} \right) \cdot \frac{P_{\text{ambient}} - P_{\text{surface}}}{P_{\text{first stop}} - P_{\text{surface}}}
$$

Deeper than the first stop the factor is clamped to $GF_{\text{low}}$; when
no stop is required the span is zero and $GF_{\text{high}}$ applies
throughout.

| Pair | Description |
| ---- | ----------- |
| `30 / 85` | conservative default |
| `50 / 95` | moderately aggressive |
| `100 / 100` | pure `Bühlmann`, no conservatism |

### The ceiling

Solving $P_{\text{tissue}} \le P_{\text{allowed}}$ for the ambient pressure,
with $M$ substituted from §5:

$$
\large P_{\text{ambient}} \ge \frac{P_{\text{tissue}} - GF \cdot a}{1 + GF \left( \frac{1}{b} - 1 \right)}
$$

At $GF = 1$ this reduces exactly to §6.

> Implemented by `_calculate_gf_limit` and `_calculate_gf_ceiling_pressure`.

## 8. Elevation

The troposphere layer of the International Standard Atmosphere, used when
the dive site — or the drive home — is above sea level:

$$
\large P(h) = P_0 \left( 1 - 2.25577 \times 10^{-5} \cdot h \right)^{5.25588}
$$

and its inverse, for reporting a pressure as an elevation:

$$
\large h = \frac{1 - \left( \dfrac{P}{P_0} \right)^{\frac{1}{5.25588}}}{2.25577 \times 10^{-5}}
$$

| Symbol | Meaning |
| ------ | ------- |
| $h$ | elevation above sea level, in meters (valid to `11,000 m`) |
| $P_0$ | `ISA` sea level pressure, `1.01325 bar` |

> The two constants are calibrated _as a set_ with $P_0 = 101325$ Pa.
> Rounding $P_0$ while keeping them gives a curve of the right shape through
> the wrong point — wrong by about `110 m` at every elevation.
>
> Implemented by `pressure_at_elevation` and `elevation_at_pressure` in
> `src/model/atmosphere.py`.

## A Note on the Retired Images

These equations previously lived in the `README` as rendered `PNG`s. Two of
them disagreed with the code:

| Retired image | Implementation |
| ------------- | -------------- |
| $M = A + B \cdot P_{\text{ambient}}$ | $M = \dfrac{P_{\text{ambient}}}{b} + a$ |
| $P_{\text{ambient min}} = \dfrac{P_{\text{tissue}} - A}{B}$ | $P_{\text{ambient}}^{\min} = \left( P_{\text{tissue}} - a \right) \cdot b$ |

Both used the convention in which $b$ is a slope. `ZHL-16` divides by it, as
the `README`'s own prose has always said. The versions above are the ones the
model evaluates.
