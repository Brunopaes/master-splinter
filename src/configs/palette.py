"""Named colour roles for every figure this project renders.

The companion to splinter.mplstyle: the style sheet dresses the canvas -
surface, grid, ink, the default cycler - and this module names the colours
that carry *meaning*, so a compartment is the same blue in a dive report as
it is in the README's teaching figures.

Nothing here should be picked by hand. The hexes are steps from a validated
dark-surface palette, and the trios below were checked with a palette
validator on the all-pairs list against SURFACE, not chosen by eye. Two
results are worth knowing before editing:

  * COMPARTMENT is three slots because three is what clears the gates. No
    fourth hue validates alongside blue, orange and aqua - the nearest
    candidates fail the normal-vision floor outright (violet against blue
    measures delta E 9.8, against a floor of 15). A figure needing a fourth
    distinguishable line needs a facet, not another colour.
  * The one accepted warning is LIMIT's green against yellow (CVD delta E
    6.9, protan). That is legal only because those two never share a line
    style - see the dashed/dash-dot split in the figure generator.

Consequently the dive report gives depth PROFILE_INK rather than a fourth
hue: depth is the frame the tissue curves are read against, on its own
axis and never compared against them, so it takes ink rather than a slot.

"""

# The chart surface the contrast checks were run against. Kept here so a
# caller drawing its own patch behind a label uses the same value the
# validator saw.
SURFACE = "#1A1A19"

# Which tissue. Stable across every figure. Keys are 0-based compartment
# indices: the fast, medium and slow representatives.
COMPARTMENT = {
    0: "#3987E5",  # fast
    7: "#D95926",  # medium
    15: "#199E70",  # slow
}

# Which ceiling, ordered by how much supersaturation it permits.
GF_CONSERVATIVE_COLOUR = "#008300"  # green,   GF 30/85
GF_MODERATE_COLOUR = "#C98500"  # yellow,  GF 50/95
MVALUE_COLOUR = "#D55181"  # magenta, the raw Bühlmann bound

# Ink. Reference lines and context are annotation rather than data and never
# take a series colour.
PROFILE_INK = "#FFFFFF"  # the dive profile itself - the frame, not a series
SECONDARY_INK = "#C3C2B7"  # direct labels, annotations
MUTED = "#898781"  # planned depth, ambient pressure, ensembles

# An event on the profile rather than a series of its own, so it is carried
# by a marker shape and a surface ring as well as by this colour.
DECO_STOP_COLOUR = "#D55181"
