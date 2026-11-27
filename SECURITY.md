# Security policy

## Reporting a vulnerability

Please report security problems **privately**, not in a public issue or pull request.

Use GitHub's private reporting: open the repository's **Security** tab and choose
**Report a vulnerability**. Only the maintainer can see the report.

Please include what you found, how to reproduce it, and which version or commit it affects.

## What to expect

This is a one-person project that is maintained largely by automation. I read private
reports as soon as I can, but I can't promise a fixed response time. A confirmed problem is
fixed on `main` and released as a new tagged version, and the report is credited unless you
ask otherwise.

## Supported versions

Only the latest tagged release and `main` receive fixes.

## How the project protects itself

Dependency updates wait out a cooldown before they merge, every GitHub Action is pinned to a
commit, and CodeQL, secret scanning with push protection and Dependabot alerts are on. The
design and its accepted risks are in [ADR 0005](docs/adr/0005-maintenance-runs-unattended-for-trusted-actors-only.md).
