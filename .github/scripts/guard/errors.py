"""Errors shared by the guard's modules."""


class GuardError(Exception):
    """The inputs are incomplete or malformed, so the guard can't judge. Fails closed."""
