"""argparse adapters over the library's bounds checking.

The rules themselves live in master_splinter.validation, next to the
constants they are checked against, so this front end cannot drift from any
other. All this module does is restate a ValueError as the exception argparse
knows how to report - which makes argparse exit 2 with the message, before any
analysis runs.

"""

import argparse
import functools

from master_splinter import validation


def _adapt(rule):
    """Wraps a library validator as an argparse type."""

    @functools.wraps(rule)
    def argparse_type(text):
        try:
            return rule(text)
        except ValueError as error:
            raise argparse.ArgumentTypeError(str(error)) from error

    return argparse_type


gradient_factors = _adapt(validation.gradient_factors)
ppo2_limit = _adapt(validation.ppo2_limit)
elevation = _adapt(validation.elevation)
