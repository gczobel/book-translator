"""Errors shared by the validator's modules."""


class ValidateError(Exception):
    """The inputs are incomplete or malformed, so the patch can't be judged. Fails closed."""
