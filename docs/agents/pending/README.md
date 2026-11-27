# Pending workflows

Workflow files that are built and tested but not yet safe to run. They live here, outside
`.github/workflows/`, so GitHub does not run them. `repair.yml` is the three-job repair workflow
for #22; see its header for what blocks it.

`release.yml` is release-please (#20). It is held back because the first `v*` tag it creates
switches off agent auto-merge (phase 2 is not built). The release config, the tag verifier
(`release-verify.yml`) and the README install section stay in place.
