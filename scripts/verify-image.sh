#!/usr/bin/env bash
set -euo pipefail
: "${IMAGE_NAME:?}" "${IMAGE_DIGEST:?}" "${EXPECTED_VERSION:?}" "${EXPECTED_REVISION:?}"
image_ref="${IMAGE_NAME}@${IMAGE_DIGEST}"
for platform in linux/amd64 linux/arm64; do
  docker pull --platform "$platform" "$image_ref"
  docker run --rm --platform "$platform" --entrypoint python \
    -e EXPECTED_VERSION -e EXPECTED_REVISION "$image_ref" -c '
import os
import server
assert server.APP_VERSION == os.environ["EXPECTED_VERSION"], "Image contains an unexpected app version"
assert os.environ.get("APP_REVISION") == os.environ["EXPECTED_REVISION"], "Image contains an unexpected commit"
print("Verified app", server.APP_VERSION, "commit", os.environ["APP_REVISION"])
'
docker image rm "$image_ref"
done
