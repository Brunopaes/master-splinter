"""Operational limits and breathing gases.

Everything here is a choice about how conservatively to dive, not a property of
the Bühlmann model (see zhl16.py) or of the water and atmosphere (see
environment.py). These are the numbers a diver or an agency would argue about.

"""

N2_FRACTION_AIR = 0.79  # Mole fraction of nitrogen in air (dimensionless)

STOP_INCREMENT = 3.0  # meters, standard spacing between decompression stops

MAX_ASCENT_RATE = 10.0  # meters per minute, standard maximum ascent rate

# Minutes to average ascent rate over. Logged profiles jitter between samples,
# and a per-sample rate reads that jitter as brief 20 m/min ascents.
ASCENT_RATE_WINDOW = 1.0

DECO_STEP = 0.5  # minutes, time resolution used when walking an ascent

# Deepest depth a loaded profile may contain, in meters. Not a statement about
# what anyone can dive: it is the point past which a logged value is far more
# likely to be a unit mix-up or a sensor spike than a real depth. Without it
# such a value reaches the model, loads the tissues past anything the stop grid
# covers, and surfaces as a RuntimeError from deep inside the ascent walk
# instead of as a complaint about the file.
MAX_PROFILE_DEPTH = 120.0

# Nitrogen fraction of each breathing gas. This model tracks nitrogen only, so
# a mix is fully described by its N2 fraction; the balance is oxygen.
GAS_MIXES = {
    "air": N2_FRACTION_AIR,
    "ean32": 0.68,
    "ean40": 0.60,
}

# Oxygen partial pressure ceilings in Bar. 1.4 is the accepted working limit,
# 1.6 the contingency limit reserved for decompression. Exceeding these risks
# CNS oxygen toxicity, which the nitrogen model itself says nothing about.
PPO2_WORKING_LIMIT = 1.4
PPO2_CONTINGENCY_LIMIT = 1.6
