# Maintenance runs unattended, for trusted actors only

The project is maintained with as little human involvement as possible, and agents write the code.
The repository is public, so rulesets, required checks, auto-merge, code scanning and secret
scanning come free. Being public also means strangers can open issues and PRs, and anything holding
a secret or able to push code is a target.

The design below was revised after an adversarial review (Trail of Bits agentic-actions-auditor,
sharp-edges and insecure-defaults, and the claude-approvals checklist). Its main lesson: **a trusted
author does not make the code trusted.** A Dependabot PR is third-party code, and an agent's PR is
code from something that may have been tricked.

## Invariants

1. **Untrusted code never runs next to write credentials.** Dependency code, and every file on a PR
   branch (including Dependabot's and our Apps'), is untrusted. No job that runs it holds an App key,
   an App token or a write-capable `GITHUB_TOKEN`.
2. **Identity is checked by numeric ID, never by login.** The PR author is checked **and** the head
   repository must equal this repository. `github.actor` and `triggering_actor` are never used.
3. **Privileged jobs read their configuration and scripts from `main`**, never from the PR branch,
   and treat PR content as data.
4. **Every gate fails closed.** A skipped, neutral, errored or truncated check counts as a failure,
   and every privileged workflow escalates when it fails or is cancelled.
5. **Agents never act with the owner's credentials.** "Owner" means the owner, typing. Agents act
   through the agent App.
6. **Text from PRs, issues, release notes and logs is data, never instructions.** The tooling enforces
   this by filtering what reaches an agent. The prompt saying so is a second line of defence.

## Identities

- **Maintenance App** (private, installed only here): release-please, pushing repairs, arming
  auto-merge, escalation issues. Each job mints a one-hour token limited to the permissions it needs.
- **Agent App**: the identity agents use to open code PRs, including local agent sessions, through a
  small helper that mints a one-hour token per session. No job ever arms its PRs automatically.
- Neither App has the Workflows permission or administration rights. No App is a bypass actor on
  `main` or on any ruleset that protects history; the maintenance App is a bypass actor only on
  `tags-create`, which cannot affect tag immutability. App keys and the Anthropic key live in
  environments that only `main` can use.

## Policy

- **Dependencies**:
  - Dependabot updates `uv` and `github-actions`. Version updates wait out a cooldown: 7 days, or 30
    for a major. Minor and patch updates are grouped, and `ignore` rules name explicit version-update
    types.
  - The arming step also checks the age of every changed lock entry against PyPI's upload time: 7
    days for version updates, **72 hours for security updates**. An owner-applied `urgent` label skips
    the 72 hours. A resolver-level `exclude-newer` cooldown covers versions pulled in indirectly.
    - Decided in #15: `pyproject.toml` sets `exclude-newer = "7 days"` (uv 0.11.21 accepts relative
      durations). Packages already locked and younger than 7 days get a temporary per-package
      override, to be deleted once they age.
    - GitHub Actions supports only `default-days` in the cooldown, so an Actions major waits 7 days,
      not 30. Dependabot dates an Actions release by the GitHub Release `published_at` of that tag,
      else the tag's creation date, else the commit date (dependabot-core,
      `common/lib/dependabot/git_cooldown_date_resolver.rb`).
    - The Dependabot cooldown applies to version updates only; security updates bypass it and are
      held back by the arming step's 72-hour age gate. `versioning-strategy: increase` raises the
      `pyproject.toml` minimum together with `uv.lock`.
  - Green updates auto-merge, majors included. The sweep re-arms only Dependabot and release-please
    PRs, and respects the kill switches.
- **Kill switches**: a `hold` label (honoured by arming and the sweep, and enforced by a required check)
  and a repository variable that pauses every privileged job. A job that can't read the variable
  pauses.
- **Vulnerabilities**:
  - Dependabot alerts and security updates, CodeQL (with a code-scanning merge rule), and secret
    scanning with push protection.
  - A daily OSV scan escalates on any of: high or critical severity, unknown severity, any malicious-
    package (`MAL-`) entry, a scan error, or an alert older than 48 hours with no open PR.
- **Pinning**:
  - Actions are pinned to commit hashes, the repository's SHA-pinning policy is on, and an
    allowed-actions list applies.
  - Downloaded tools are pinned by version and checksum, or locked through `uv.lock`.
  - zizmor runs with online audits, on the workflows and on the Dependabot config.
  - Updates to the actions that handle secrets need the owner.
- **Required checks**: lint, typecheck, test, e2e (in place from day one, filled in when the
  translator exists), epubcheck, workflow-security, the repair guard and `hold`.
  - They are aggregator jobs that check every upstream result.
  - Each is pinned to the GitHub Actions app as its source.
  - Their names are unique across workflows.
- **Releases**: release-please, using the maintenance App, with blank squash commit bodies.
  - Two tag rulesets on `v*` (decided in #14): `tags-immutable` blocks moving or deleting tags and has
    no bypass actors; `tags-create` blocks creation and lets only the maintenance App bypass. A bypass
    actor skips every rule of the ruleset it is listed on, so the split lets the App create tags
    without ever being able to move or delete one. The rulesets live in `.github/rulesets/` and are
    applied with `.github/scripts/apply-rulesets.sh`.
    The same script sets the repository Actions setting that makes every fork PR run wait for the
    owner's approval (`all_external_contributors`).
  - A job verifies that each new tag points at a release-please merge on `main`.
- **Repairs**: when a Dependabot or release PR fails CI, three jobs run.
  1. **agent**: only the Anthropic key; read-only token; no caches; restricted network; Claude Code
     without project settings. Bash only for `uv sync --locked` and `uv run pytest`, and no `gh` or
     `git push`. It outputs a patch.
  2. **validate**: no secrets, and it runs no PR code. It enforces the repair allowlist (`src/**` and
     dependency lines only) and the test-ID ratchet, and rejects high-entropy strings.
  3. **push**: a contents-only token. It applies the validated patch.

  There are at most 2 attempts per PR, counted from commits, with one concurrency group per PR. The
  Anthropic key belongs to a dedicated Console workspace with a low monthly limit and usage alerts.
  Running out of budget escalates.
- **Code PRs from agents**: they need CI, the deterministic guard, and an LLM review that may block
  but never approve.
  - **Until the first release** they auto-merge when those pass.
    - Decided in #25: this is a **temporary deviation** from the above. The LLM reviewer is not built,
      so until it exists agent code merges after CI and the guard only, without the LLM review
      phase 1 assumed. The merge rule names this as one constant (`LLM_REVIEW_REQUIRED` in
      `agentpr/core.py`). The `agent-pr-review` job stays as a placeholder that fails on every
      agent PR, so adding `llm-review` as a required check before a real reviewer exists blocks
      instead of silently passing. #25 stays open until the real reviewer exists, at which point
      the constant is switched on.
  - **From the first release on**, each waits for the owner's approval. The switch happens with the
    first `v*` tag.
  - **At any phase**, guarded paths need the owner's approval on the head commit.
  - Agents act only on issues the owner wrote, and other people's comments are filtered out.
- **Guarded paths**:
  - `.github/**`, `**/.claude/**`, `**/REVIEW.md`, `AGENTS.md`, `CLAUDE.md`, `docs/agents/**`,
    `docs/adr/**`, `.mcp.json`, the release-please files, CI scripts, `.gitattributes`, `.gitmodules`,
    `.python-version`.
  - Any symlink, and any change to `[tool.uv]` or `[build-system]` or to lock-file source URLs.
  - One exception: Dependabot's own pin updates in workflow files, checked line by line.
- **Python** stays on the version all our libraries support best (3.13 at the start). A non-blocking
  weekly job tests the next version and escalates once it passes.
- **Escalation**: an issue labelled `ready-for-human`, assigned to the owner. It is matched only when
  the maintenance App wrote it and it carries a hidden marker. Issues written by anyone else are never
  updated or reopened.

## Accepted risks

- **OpenSSF Scorecard** will score Code-Review and Branch-Protection low, because review is
  automated on purpose. It will flag the repair's `workflow_run` trigger as a dangerous workflow; the
  three-job split is the reviewed mitigation.
- **Before the first release**, agent code PRs merge without a human review. An injected agent could
  land malicious code that passes every check. The mitigations are the input filtering, the guarded
  paths, and the fact that no released code or users exist yet.
- **The 72-hour minimum age** delays genuine security fixes unless the owner applies `urgent`.

## Considered Options

- **Private repo with workarounds** (merge-after-CI workflow, Semgrep and gitleaks): weaker, and
  more custom code to maintain.
- **Renovate**: a stronger cooldown and a dashboard, but a separate app, and unlike the owner's
  other repositories.
- **Claude Approvals** as the code-PR gate: it only runs on Claude Team or Enterprise plans, so on
  this account it would guard nothing. A deterministic guard plus the owner's approval replaces it.
- **One App for everything**: simpler, but any token it mints could open a PR that merges itself.
