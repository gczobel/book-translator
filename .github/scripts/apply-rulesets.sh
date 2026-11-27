#!/usr/bin/env bash
# Create or update the repository rulesets from .github/rulesets/*.json (ADR 0005).
# Run by the owner, authenticated with admin rights: `.github/scripts/apply-rulesets.sh`.
# Idempotent: a ruleset is matched by name and replaced.
set -euo pipefail

repo="${REPO:-$(gh repo view --json nameWithOwner -q .nameWithOwner)}"
dir="$(cd "$(dirname "$0")/../rulesets" && pwd)"

for file in "$dir"/*.json; do
  name="$(jq -r .name "$file")"
  id="$(gh api "repos/$repo/rulesets" --jq ".[] | select(.name == \"$name\") | .id")"
  if [ -n "$id" ]; then
    gh api --method PUT "repos/$repo/rulesets/$id" --input "$file" --silent
    echo "updated $name ($id)"
  else
    gh api --method POST "repos/$repo/rulesets" --input "$file" --silent
    echo "created $name"
  fi
done
