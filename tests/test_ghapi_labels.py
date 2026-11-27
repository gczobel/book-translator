"""The one `hold` rule shared by arming and the agent merge rule."""

import pytest

from ghapi.labels import is_on_hold


@pytest.mark.parametrize("labels", [["hold"], ["Hold"], ["HOLD", "x"], ("bug", "hOLd")])
def test_any_case_of_hold_holds(labels: list[str]) -> None:
    assert is_on_hold(labels)


@pytest.mark.parametrize("labels", [[], ["holding"], ["on hold"], ["bug"]])
def test_other_labels_do_not(labels: list[str]) -> None:
    assert not is_on_hold(labels)
