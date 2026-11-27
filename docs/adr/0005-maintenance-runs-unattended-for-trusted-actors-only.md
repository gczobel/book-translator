# Maintenance runs unattended, for trusted actors only

The project is maintained with as little human involvement as possible, the code included.
The repository is public so that rulesets, required checks, auto-merge, CodeQL and secret
scanning come free. Being public also means strangers can open issues and PRs, so every
automation that holds a secret or can push code acts only for trusted actors.

## Policy

- **Dependencies**: Dependabot updates the `uv` and `github-actions` ecosystems. A version is
  only proposed once it has been out 7 days (30 days for a major). Minor and patch updates are
  grouped. Security updates skip the cooldown, as Dependabot's cooldown applies to version
  updates only. Every update auto-merges once the required checks pass, majors included.
  A sweep re-arms auto-merge on open bot PRs after each push to `main` and once a day.
- **Vulnerabilities**: Dependabot alerts and security updates are on. A daily OSV scan of
  `uv.lock` opens an issue when a high or critical CVE has no fix yet. CodeQL, secret scanning
  and push protection are enabled.
- **Required checks**: ruff, pyright, pytest, an end-to-end run on a public-domain fixture with
  LLM responses recorded at our own interface (never live API calls), and epubcheck on its output.
- **Actions are pinned to commit SHAs**. Dependabot updates the hash and its version comment,
  and zizmor fails CI on unpinned actions or risky workflow patterns.
- **Python** stays on the version all our libraries support best (3.13 at the start). A weekly
  job tests the next version and opens an issue once it passes.
- **Releases**: release-please builds versions and changelogs from Conventional Commits.
  Its PRs auto-merge like the rest.
- **Repairs**: when a bot PR fails CI, claude-code-action reads the log and pushes a fix to
  that PR's branch. It has at most 2 attempts and a monthly spending cap. It may never touch
  guarded paths, and it may never delete, skip or weaken a test.
- **Code PRs**: agent PRs auto-merge after CI and an automated review pass (Claude Approvals).
  PRs that touch guarded paths need the owner: `.github/workflows/`, the dependency and
  approval policies, rulesets, `AGENTS.md`/`CLAUDE.md`, `docs/adr/`.
- **Escalation**: anything automation gives up on becomes an issue labelled `ready-for-human`
  and assigned to the owner. That is the only channel that asks for attention.

## Trust boundary

- Workflows that use the Anthropic API key or a write-capable token run only when the actor
  or PR author is `dependabot[bot]`, release-please's app, or the owner. They check this
  explicitly in their `if:`.
- They never run on issue or PR comments from others, and never use `pull_request_target` or
  `workflow_run` to act on code from forks.
- PR text, issue text and CI logs reaching the agent are treated as untrusted data, never
  as instructions.
- PRs created by automation need a GitHub App token, because PRs opened with `GITHUB_TOKEN`
  don't trigger CI and would never satisfy the required checks.
- Workflow runs from outside contributors' forks need the owner's approval before they run.

## Considered Options

- **Private repo with workarounds** (merge-after-CI workflow, Semgrep and gitleaks instead of
  CodeQL and push protection): weaker, and more custom code to maintain.
- **Renovate** instead of Dependabot: a stronger cooldown and a dashboard, but a separate app
  and unlike the owner's other repositories.
