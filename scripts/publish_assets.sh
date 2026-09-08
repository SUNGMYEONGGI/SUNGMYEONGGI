#!/usr/bin/env bash
# Run after rendering succeeds. Only the generated branch receives commits.
set -euo pipefail
: "${TOKEN_OUTPUT:?Set TOKEN_OUTPUT to the rendered image directory}"
: "${TOKEN_PUBLISH:?Set TOKEN_PUBLISH to a fresh temporary worktree path}"

test -s "$TOKEN_OUTPUT/token-activity-light.svg"
test -s "$TOKEN_OUTPUT/token-activity-dark.svg"
git fetch origin token-assets
git worktree add --detach "$TOKEN_PUBLISH" origin/token-assets
trap 'git worktree remove --force "$TOKEN_PUBLISH"' EXIT
mkdir -p "$TOKEN_PUBLISH/assets"
cp "$TOKEN_OUTPUT/token-activity-light.svg" "$TOKEN_PUBLISH/assets/"
cp "$TOKEN_OUTPUT/token-activity-dark.svg" "$TOKEN_PUBLISH/assets/"
git -C "$TOKEN_PUBLISH" add -- assets/token-activity-light.svg assets/token-activity-dark.svg
if git -C "$TOKEN_PUBLISH" diff --cached --quiet; then
  echo "Token grass is already current."
  exit 0
fi
git -C "$TOKEN_PUBLISH" -c user.name='github-actions[bot]' \
  -c user.email='41898282+github-actions[bot]@users.noreply.github.com' \
  commit -m 'chore: refresh token activity'
git -C "$TOKEN_PUBLISH" push origin HEAD:refs/heads/token-assets
