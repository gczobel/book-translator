#!/usr/bin/env bash
# Create or update the repository rulesets from .github/rulesets/*.json (ADR 0005).
# Run by the owner, authenticated with admin rights: `.github/scripts/apply-rulesets.sh`.
# Idempotent: a ruleset is matched by name and replaced. It never deletes rulesets.
# IDs used in the JSON: 15368 is the GitHub Actions app (pins each required check);
# 5952645 is the maintenance App (the only bypass actor, on tags-create).
set -euo pipefail

repo="${REPO:-$(gh repo view --json nameWithOwner -q .nameWithOwner)}"
dir="$(cd "$(dirname "$0")/../rulesets" && pwd)"

for file in "$dir"/*.json; do
  name="$(jq -r .name "$file")"
  id="$(gh api "repos/$repo/rulesets" | jq -r --arg n "$name" '.[] | select(.name == $n) | .id')"
  if [ -n "$id" ]; then
    gh api --method PUT "repos/$repo/rulesets/$id" --input "$file" --silent
    echo "updated $name ($id)"
  else
    gh api --method POST "repos/$repo/rulesets" --input "$file" --silent
    echo "created $name"
  fi
done

# Squash merges carry the PR title and a blank body, so no commit body (a `BREAKING CHANGE:`
# footer, a second `feat:` line) can steer release-please's version bump (ticket #20).
gh api --method PATCH "repos/$repo" \
  -f squash_merge_commit_title=PR_TITLE -f squash_merge_commit_message=BLANK --silent
echo "squash merge commits: PR title, blank body"

# Fork PR runs need the owner's approval (a repository Actions setting, not a ruleset).
gh api --method PUT "repos/$repo/actions/permissions/fork-pr-contributor-approval" \
  -f approval_policy=all_external_contributors --silent
echo "fork PR approval: all_external_contributors"
