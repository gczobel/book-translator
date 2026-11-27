"""Read the PAUSE variable from the environment and publish the decision as step outputs."""

from __future__ import annotations

from collections.abc import Mapping

from pause.core import decide


def run(env: Mapping[str, str]) -> int:
    """Write `state` and `paused` to $GITHUB_OUTPUT. Non-zero if they can't be written.

    A failing step leaves the outputs empty, and callers only proceed on `paused == 'false'`,
    so a crash here keeps automation stopped.
    """
    decision = decide(env.get("PAUSE_VALUE"))
    path = env.get("GITHUB_OUTPUT")
    if not path:
        print("pause: GITHUB_OUTPUT is not set")
        return 1
    try:
        with open(path, "a", encoding="utf-8") as out:
            out.write(f"state={decision.state}\npaused={str(decision.paused).lower()}\n")
    except OSError:
        print("pause: cannot write the step outputs")
        return 1
    print(f"pause: {decision.state}")
    return 0
