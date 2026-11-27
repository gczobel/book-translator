"""Entry point: validate the request, escalate, exit non-zero on any failure."""

from __future__ import annotations

from collections.abc import Mapping

from escalate.core import Api, EscalationError, escalate, parse_request
from ghapi.client import ApiError, HttpApi


def run(env: Mapping[str, str], api: Api | None = None) -> int:
    """0 if the issue was opened or updated. A failure to escalate must itself be loud."""
    try:
        request = parse_request(env)
        if api is None:
            token = env.get("GH_TOKEN", "")
            if not token:
                raise EscalationError("GH_TOKEN is missing")
            api = HttpApi(token)
        print(f"escalate: {escalate(api, env['GITHUB_REPOSITORY'], request)}")
    except (EscalationError, ApiError) as error:
        print(f"escalate: FAILED: {error}")
        return 1
    except Exception as error:
        print(f"escalate: FAILED: unexpected {type(error).__name__}")
        return 1
    return 0
