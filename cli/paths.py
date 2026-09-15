"""Where the commands keep things, when the user does not say.

The library deliberately has no default state location - every state_store
entry point takes an explicit path, because a library that picked one would
be writing next to its own installed source. Choosing a default is a front
end's job, and this is where this front end chooses.

"""

import os
from pathlib import Path

# Rendered output goes to the working directory. A dive report is something
# the user asked for now, not an artifact of the installation.
DEFAULT_OUTPUT = Path("dive_simulation.png")

_STATE_FILE = "state.json"


def default_state_path():
    """Tissue state location, following the XDG state directory spec.

    Notes:
    ------
    State rather than config or cache: it is written by the program, not the
    user, and losing it silently loses a diver's residual loading. $XDG_STATE_HOME
    when set and absolute, otherwise ~/.local/state.

    """
    configured = os.environ.get("XDG_STATE_HOME")
    root = (
        Path(configured)
        if configured and Path(configured).is_absolute()
        else Path.home() / ".local" / "state"
    )
    return root / "master-splinter" / _STATE_FILE
