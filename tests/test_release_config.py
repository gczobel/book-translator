"""The release-please files and the tag verification must agree with each other."""

import json
import tomllib
from pathlib import Path
from typing import Any

from releasetag.core import RELEASE_BRANCH_PREFIX, TITLE_PATTERN

ROOT = Path(__file__).resolve().parent.parent


def _config() -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads((ROOT / "release-please-config.json").read_text())
    return loaded


def test_the_title_the_verifier_expects_is_the_title_release_please_writes() -> None:
    assert _config()["pull-request-title-pattern"] == TITLE_PATTERN


def test_tags_are_plain_v_versions_with_no_component() -> None:
    config = _config()
    assert config["include-v-in-tag"] is True
    assert config["include-component-in-tag"] is False


def test_the_branch_prefix_belongs_to_the_target_branch() -> None:
    assert RELEASE_BRANCH_PREFIX == "release-please--branches--"


def test_arming_and_tag_verification_agree_on_release_pleases_branch() -> None:
    from arming.core import ARMABLE_AUTHORS
    from ghapi.identities import MAINT_BOT_ID

    assert RELEASE_BRANCH_PREFIX.startswith(ARMABLE_AUTHORS[MAINT_BOT_ID])


def test_the_manifest_starts_at_the_version_in_pyproject() -> None:
    manifest = json.loads((ROOT / ".release-please-manifest.json").read_text())
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text())
    assert manifest == {".": pyproject["project"]["version"]}


def test_the_lock_file_version_is_bumped_with_the_release() -> None:
    (package,) = _config()["packages"].values()
    assert any(f["path"] == "uv.lock" and f["type"] == "toml" for f in package["extra-files"])
