#!/usr/bin/env bash
set -euo pipefail
: "${IMAGE_NAME:?}" "${IMAGE_DIGEST:?}" "${GITHUB_SHA:?}" "${GITHUB_REF:?}"
# Tags, other branches, and reruns of old main commits cannot roll latest back.
if [[ "$GITHUB_REF" != refs/heads/main ]]; then
  exit 0
fi
current_main="$(git ls-remote --exit-code origin refs/heads/main | cut -f1)"
if [[ "$current_main" != "$GITHUB_SHA" ]]; then
  printf 'Skipping latest: main has moved to %s.\n' "$current_main"
  exit 0
fi
docker buildx imagetools create --tag "${IMAGE_NAME}:latest" "${IMAGE_NAME}@${IMAGE_DIGEST}"
latest_digest="$(docker buildx imagetools inspect "${IMAGE_NAME}:latest" --format '{{.Manifest.Digest}}')"
if [[ "$latest_digest" != "$IMAGE_DIGEST" ]]; then
  printf 'latest digest mismatch: expected %s, got %s\n' "$IMAGE_DIGEST" "$latest_digest" >&2
  exit 1
fi
printf 'Verified latest: %s@%s\n' "$IMAGE_NAME" "$latest_digest"
if [[ -n "${GITHUB_STEP_SUMMARY:-}" ]]; then
  printf 'Published `%s:latest` from commit `%s`.\n\nVerified digest: `%s`\n' "$IMAGE_NAME" "$GITHUB_SHA" "$latest_digest" >> "$GITHUB_STEP_SUMMARY"
fi
