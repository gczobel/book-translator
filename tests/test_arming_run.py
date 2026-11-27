"""The arming steps end to end against a fake GitHub. Seam: `arming.run.select` / `arm`."""

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from arming.core import REQUIRED_CHECKS
from arming.run import CLEAN_STATUS, arm, select
from ghapi.client import ApiError
from ghapi.identities import ACTIONS_APP_ID, DEPENDABOT_ID, OWNER_ID

REPO = "o/r"
SHA = "b" * 40


def raw_pull(number: int = 7, **over: Any) -> dict[str, Any]:
    item: dict[str, Any] = {
        "number": number,
        "node_id": f"PR_{number}",
        "state": "open",
        "user": {"id": DEPENDABOT_ID},
        "head": {"repo": {"full_name": REPO}, "ref": "dependabot/uv/x", "sha": SHA},
        "base": {"repo": {"full_name": REPO}, "ref": "main"},
        "labels": [{"name": "dependencies"}],
        "auto_merge": None,
    }
    item.update(over)
    return item


def green_checks(**over: Any) -> dict[str, Any]:
    """A check-runs reply with every required check successful, except as `over` changes it."""
    runs = [
        {
            "id": i,
            "name": n,
            "status": "completed",
            "conclusion": "success",
            "app": {"id": ACTIONS_APP_ID},
        }
        for i, n in enumerate(REQUIRED_CHECKS, start=1)
    ]
    return {"total_count": len(runs), "check_runs": runs, **over}


class FakeApi:
    def __init__(self, pulls: list[dict[str, Any]] | None = None) -> None:
        self.pulls = pulls if pulls is not None else [raw_pull()]
        self.events: dict[int, list[dict[str, Any]]] = {}
        self.lock: str | None = "lock"
        self.posts: list[tuple[str, dict[str, Any]]] = []
        self.graphql_replies: list[Any] = []
        self.fail_pages = False
        self.check_runs: Any = green_checks()

    def get_json(self, path: str) -> Any:
        if path == f"/repos/{REPO}":
            return {"default_branch": "main"}
        if "/check-runs" in path:
            return self.check_runs
        number = int(path.rsplit("/", 1)[1])
        return next(p for p in self.pulls if p["number"] == number)

    def get_pages(self, path: str) -> list[Any]:
        if self.fail_pages:
            raise ApiError("boom")
        if path.startswith(f"/repos/{REPO}/pulls"):
            return self.pulls
        number = int(path.split("/")[5])
        return self.events.get(number, [])

    def get_text(self, path: str) -> str | None:
        assert path == f"/repos/{REPO}/contents/uv.lock?ref={SHA}"
        return self.lock

    def post_json(self, path: str, payload: dict[str, Any]) -> Any:
        assert path == "/graphql"
        self.posts.append((path, payload))
        return self.graphql_replies.pop(0) if self.graphql_replies else {"data": {}}


def env(tmp_path: Path, **extra: str) -> dict[str, str]:
    base = tmp_path / "base.lock"
    base.write_text("base")
    out = tmp_path / "out"
    out.write_text("")
    return {
        "GITHUB_REPOSITORY": REPO,
        "GITHUB_OUTPUT": str(out),
        "ARMING_BASE_LOCK": str(base),
        "ARMING_WORKDIR": str(tmp_path),
        **extra,
    }


def outputs(tmp_path: Path) -> dict[str, str]:
    lines = (tmp_path / "out").read_text().splitlines()
    return dict(line.split("=", 1) for line in lines)


class Gate:
    def __init__(self, code: int = 0) -> None:
        self.code = code
        self.calls: list[Mapping[str, str]] = []

    def __call__(self, e: Mapping[str, str]) -> int:
        self.calls.append(dict(e))
        return self.code


def test_a_qualifying_pr_that_passes_the_age_gate_is_selected(tmp_path: Path) -> None:
    gate = Gate()
    assert select(env(tmp_path), FakeApi(), gate) == 0
    out = outputs(tmp_path)
    assert json.loads(out["armable"]) == [
        {"number": 7, "head_sha": SHA, "security": False, "urgent": False}
    ]
    assert json.loads(out["disarm"]) == [] and out["work"] == "true"
    assert out["ok"] == "true"
    call = gate.calls[0]
    assert call["IS_SECURITY"] == "false" and call["URGENT"] == "false"
    assert Path(call["HEAD_LOCK"]).read_text() == "lock"  # fetched as data at the head sha
    assert call["BASE_LOCK"] == str(tmp_path / "base.lock")
    assert "GITHUB_OUTPUT" not in call


def test_a_pr_that_fails_the_age_gate_is_left_alone(tmp_path: Path) -> None:
    assert select(env(tmp_path), FakeApi(), Gate(1)) == 0
    out = outputs(tmp_path)
    assert json.loads(out["armable"]) == []
    assert out["ok"] == "true"


def test_non_candidates_never_reach_the_age_gate(tmp_path: Path) -> None:
    pulls = [raw_pull(1, user={"id": 5}), raw_pull(2, labels=[{"name": "hold"}])]
    gate = Gate()
    select(env(tmp_path), FakeApi(pulls), gate)
    assert gate.calls == []


def test_security_and_urgent_are_passed_to_the_gate(tmp_path: Path) -> None:
    pulls = [raw_pull(labels=[{"name": "security"}, {"name": "urgent"}])]
    api = FakeApi(pulls)
    api.events[7] = [
        {"event": "labeled", "label": {"name": "security"}, "actor": {"id": DEPENDABOT_ID}},
        {"event": "labeled", "label": {"name": "urgent"}, "actor": {"id": OWNER_ID}},
    ]
    gate = Gate()
    select(env(tmp_path), api, gate)
    assert gate.calls[0]["IS_SECURITY"] == "true" and gate.calls[0]["URGENT"] == "true"


def test_a_missing_head_lock_means_not_armed_and_not_ok(tmp_path: Path) -> None:
    api = FakeApi()
    api.lock = None
    assert select(env(tmp_path), api, Gate()) == 0
    out = outputs(tmp_path)
    assert json.loads(out["armable"]) == []
    assert out["ok"] == "false"


def test_a_failed_listing_publishes_nothing_armable(tmp_path: Path) -> None:
    api = FakeApi()
    api.fail_pages = True
    assert select(env(tmp_path), api, Gate()) == 0
    out = outputs(tmp_path)
    assert json.loads(out["armable"]) == []
    assert out["ok"] == "false"


def test_a_crashing_gate_is_not_a_pass(tmp_path: Path) -> None:
    def boom(_: Mapping[str, str]) -> int:
        raise RuntimeError("x")

    select(env(tmp_path), FakeApi(), boom)
    out = outputs(tmp_path)
    assert json.loads(out["armable"]) == []
    assert out["ok"] == "false"


def targets(*items: dict[str, Any]) -> dict[str, str]:
    full = [{"security": False, "urgent": False, **item} for item in items]
    return {"ARMING_TARGETS": json.dumps(full)}


def test_arm_enables_squash_auto_merge_with_a_blank_body_pinned_to_the_head(
    tmp_path: Path,
) -> None:
    api = FakeApi()
    assert arm(env(tmp_path, **targets({"number": 7, "head_sha": SHA})), api) == 0
    assert len(api.posts) == 1
    payload = api.posts[0][1]
    assert "enablePullRequestAutoMerge" in payload["query"]
    assert "SQUASH" in payload["query"] and 'commitBody: ""' in payload["query"]
    assert payload["variables"] == {"id": "PR_7", "oid": SHA}


def clean(api: FakeApi) -> FakeApi:
    api.graphql_replies = [{"errors": [{"message": f"Pull request is in {CLEAN_STATUS}"}]}]
    return api


def test_arm_merges_directly_when_clean_and_every_required_check_succeeded(tmp_path: Path) -> None:
    api = clean(FakeApi())
    assert arm(env(tmp_path, **targets({"number": 7, "head_sha": SHA})), api) == 0
    assert "mergePullRequest" in api.posts[1][1]["query"]
    assert 'commitBody: ""' in api.posts[1][1]["query"]


def _with(name: str, **changes: Any) -> dict[str, Any]:
    reply = green_checks()
    for run in reply["check_runs"]:
        if run["name"] == name:
            run.update(changes)
    return reply


def _without(name: str) -> dict[str, Any]:
    reply = green_checks()
    reply["check_runs"] = [r for r in reply["check_runs"] if r["name"] != name]
    reply["total_count"] = len(reply["check_runs"])
    return reply


def test_arm_does_not_merge_a_clean_pr_unless_every_required_check_is_verified(
    tmp_path: Path,
) -> None:
    cases: list[Any] = []
    for name in REQUIRED_CHECKS:
        cases += [
            _without(name),
            _with(name, conclusion="failure"),
            _with(name, conclusion="skipped"),
            _with(name, conclusion="neutral"),
            _with(name, conclusion=None, status="in_progress"),
            _with(name, app={"id": ACTIONS_APP_ID + 1}),  # not from GitHub Actions
        ]
    for reply in cases:
        api = clean(FakeApi())
        api.check_runs = reply
        # Nothing is merged, and it is not a failure: the next sweep retries.
        assert arm(env(tmp_path, **targets({"number": 7, "head_sha": SHA})), api) == 0
        assert len(api.posts) == 1, reply


def test_a_newer_run_of_a_check_supersedes_an_older_failure(tmp_path: Path) -> None:
    reply = green_checks()
    reply["check_runs"].append(
        {
            "id": 999,
            "name": "lint",
            "status": "completed",
            "conclusion": "failure",
            "app": {"id": ACTIONS_APP_ID},
        }
    )
    reply["total_count"] += 1
    api = clean(FakeApi())
    api.check_runs = reply
    arm(env(tmp_path, **targets({"number": 7, "head_sha": SHA})), api)
    assert len(api.posts) == 1  # the newest lint run failed


def test_unreadable_check_runs_fail_closed_without_merging(tmp_path: Path) -> None:
    unreadable: list[Any] = [[], {"total_count": "x"}, {"total_count": 5, "check_runs": []}]
    for bad in unreadable:
        api = clean(FakeApi())
        api.check_runs = bad
        assert arm(env(tmp_path, **targets({"number": 7, "head_sha": SHA})), api) == 1
        assert len(api.posts) == 1


def test_arm_fails_on_other_graphql_errors(tmp_path: Path) -> None:
    api = FakeApi()
    api.graphql_replies = [{"errors": [{"message": "Auto merge is not allowed"}]}]
    assert arm(env(tmp_path, **targets({"number": 7, "head_sha": SHA})), api) == 1
    assert len(api.posts) == 1


def test_arm_refuses_a_pr_that_moved_or_gained_hold_since_selection(tmp_path: Path) -> None:
    head = {"repo": {"full_name": REPO}, "ref": "dependabot/x", "sha": "c" * 40}
    moved = FakeApi([raw_pull(head=head)])
    assert arm(env(tmp_path, **targets({"number": 7, "head_sha": SHA})), moved) == 1
    held = FakeApi([raw_pull(labels=[{"name": "hold"}])])
    assert arm(env(tmp_path, **targets({"number": 7, "head_sha": SHA})), held) == 1
    assert moved.posts == [] and held.posts == []


def test_arm_rejects_malformed_targets(tmp_path: Path) -> None:
    for bad in ["not json", '{"a": 1}', '[{"number": "7", "head_sha": "x"}]', '[{"number": 7}]']:
        api = FakeApi()
        assert arm(env(tmp_path, ARMING_TARGETS=bad), api) == 1
        assert api.posts == []


def test_arm_with_nothing_to_do_succeeds(tmp_path: Path) -> None:
    assert arm(env(tmp_path, ARMING_TARGETS="[]"), FakeApi()) == 0


# --- an armed PR must not escape the age gate ---------------------------------------------------


def armed(**over: Any) -> dict[str, Any]:
    return raw_pull(auto_merge={"enabled_by": {}}, **over)


def test_an_armed_pr_that_still_qualifies_is_left_armed(tmp_path: Path) -> None:
    gate = Gate()
    assert select(env(tmp_path), FakeApi([armed()]), gate) == 0
    out = outputs(tmp_path)
    assert gate.calls  # it was judged again against its current head
    assert json.loads(out["armable"]) == [] and json.loads(out["disarm"]) == []
    assert out["work"] == "false"


def test_an_armed_pr_whose_head_now_fails_the_age_gate_is_disarmed(tmp_path: Path) -> None:
    assert select(env(tmp_path), FakeApi([armed()]), Gate(1)) == 0
    out = outputs(tmp_path)
    assert json.loads(out["disarm"]) == [7] and out["work"] == "true"
    assert json.loads(out["armable"]) == []


def test_an_armed_pr_that_no_longer_qualifies_is_disarmed(tmp_path: Path) -> None:
    gate = Gate()
    select(env(tmp_path), FakeApi([armed(labels=[{"name": "Hold"}])]), gate)
    assert json.loads(outputs(tmp_path)["disarm"]) == [7]
    assert gate.calls == []  # no need to run the gate


def test_an_armed_pr_that_cannot_be_checked_is_disarmed_and_not_ok(tmp_path: Path) -> None:
    api = FakeApi([armed()])
    api.lock = None
    select(env(tmp_path), api, Gate())
    out = outputs(tmp_path)
    assert json.loads(out["disarm"]) == [7] and out["ok"] == "false"


def test_someone_elses_armed_pr_is_never_disarmed(tmp_path: Path) -> None:
    select(env(tmp_path), FakeApi([armed(user={"id": OWNER_ID})]), Gate(1))
    assert json.loads(outputs(tmp_path)["disarm"]) == []


def test_arm_disables_auto_merge_on_the_listed_armed_prs(tmp_path: Path) -> None:
    api = FakeApi([armed()])
    code = arm(env(tmp_path, ARMING_TARGETS="[]", ARMING_DISARM="[7]"), api)
    assert code == 0
    assert "disablePullRequestAutoMerge" in api.posts[0][1]["query"]
    assert api.posts[0][1]["variables"] == {"id": "PR_7"}


def test_arm_does_not_disable_what_is_not_armed_or_not_ours(tmp_path: Path) -> None:
    for pull in (raw_pull(), armed(user={"id": OWNER_ID})):
        api = FakeApi([pull])
        assert arm(env(tmp_path, ARMING_TARGETS="[]", ARMING_DISARM="[7]"), api) == 0
        assert api.posts == []


def test_a_failed_disable_fails_the_job(tmp_path: Path) -> None:
    api = FakeApi([armed()])
    api.graphql_replies = [{"errors": [{"message": "nope"}]}]
    assert arm(env(tmp_path, ARMING_TARGETS="[]", ARMING_DISARM="[7]"), api) == 1
    assert arm(env(tmp_path, ARMING_TARGETS="[]", ARMING_DISARM="oops"), api) == 1


# --- arm refuses a stricter label state than select used ---------------------------------------


def test_arm_refuses_when_a_label_the_age_gate_relied_on_is_gone(tmp_path: Path) -> None:
    for relied in ({"security": True}, {"urgent": True}):
        api = FakeApi()  # the live PR has neither label honoured
        item = targets({"number": 7, "head_sha": SHA, **relied})
        assert arm(env(tmp_path, **item), api) == 1
        assert api.posts == []


def test_arm_accepts_labels_equal_to_or_looser_than_what_select_used(tmp_path: Path) -> None:
    pulls = [raw_pull(labels=[{"name": "security"}, {"name": "urgent"}])]
    api = FakeApi(pulls)
    api.events[7] = [
        {"event": "labeled", "label": {"name": "security"}, "actor": {"id": DEPENDABOT_ID}},
        {"event": "labeled", "label": {"name": "urgent"}, "actor": {"id": OWNER_ID}},
    ]
    both = targets({"number": 7, "head_sha": SHA, "security": True, "urgent": True})
    assert arm(env(tmp_path, **both), api) == 0
    api2 = FakeApi(pulls)
    api2.events[7] = api.events[7]
    assert arm(env(tmp_path, **targets({"number": 7, "head_sha": SHA})), api2) == 0


def test_arm_rejects_targets_without_the_label_state(tmp_path: Path) -> None:
    bad = json.dumps([{"number": 7, "head_sha": SHA}])
    api = FakeApi()
    assert arm(env(tmp_path, ARMING_TARGETS=bad), api) == 1
    assert api.posts == []
