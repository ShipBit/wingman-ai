#!/usr/bin/env bash
# Uploads one platform of a Core build to R2 staging and prunes old builds.
#
#   stage-core.sh <channel> <platform> <dir>
#
# Layout: core/<channel>/<sha>/<platform>/, and core/<channel>/latest-<os>.txt
# naming the newest SHA per platform. The client's download-core action reads
# the same layout. Each channel has its own prefix, so an unstable and a
# production build of the same or of different commits never touch each other,
# and both can run at the same time.
#
# Pruning stays inside the channel: it keeps the newest KEEP_BUILDS builds
# (default 5, by the upload time of their Core binary), the one just staged and
# whatever the channel's pointers name. Staging must not grow forever, but a
# client release started a little later still finds its Core.
#
# Needs GITHUB_SHA, R2_ACCOUNT_ID and the AWS_* variables for R2.
set -euo pipefail

CHANNEL=$1
PLATFORM=$2
SRC=$3

case "$CHANNEL" in
  unstable|production) ;;
  *) echo "::error::Unknown channel '$CHANNEL'"; exit 1 ;;
esac
case "$PLATFORM" in
  windows-x86_64) OS=windows ;;
  darwin-aarch64) OS=macos ;;
  linux-x86_64) OS=linux ;;
  *) echo "::error::Unknown platform '$PLATFORM'"; exit 1 ;;
esac

SHA=${GITHUB_SHA:?}
KEEP=${KEEP_BUILDS:-5}
ENDPOINT="https://${R2_ACCOUNT_ID:?}.r2.cloudflarestorage.com"
ROOT="s3://wingman-staging/core"
BASE="$ROOT/$CHANNEL"

s3() { aws s3 "$@" --endpoint-url "$ENDPOINT"; }

s3 cp "$SRC/" "$BASE/$SHA/$PLATFORM/" --recursive --only-show-errors
echo "$SHA" > "latest-$OS.txt"
s3 cp "latest-$OS.txt" "$BASE/latest-$OS.txt" --only-show-errors
echo "Staged core/$CHANNEL/$SHA/$PLATFORM/"

# This channel's builds, newest first. A build still uploading has no binary
# listed yet and is left alone.
BUILDS=$(s3 ls "$BASE/" --recursive \
  | grep -E '/WingmanAiCore(\.exe)?$' \
  | awk '{ split($4, part, "/"); print $1 "T" $2, part[3] }' \
  | sort -r | awk '!seen[$2]++ { print $2 }')

POINTED=""
for os in windows macos linux; do
  POINTED="$POINTED $(s3 cp "$BASE/latest-$os.txt" - 2>/dev/null || true)"
done

n=0
for BUILD in $BUILDS; do
  n=$((n + 1))
  if [ "$BUILD" = "$SHA" ] || [ "$n" -le "$KEEP" ] || [[ " $POINTED " == *" $BUILD "* ]]; then
    continue
  fi
  echo "Deleting old staging build core/$CHANNEL/$BUILD/"
  s3 rm "$BASE/$BUILD/" --recursive --only-show-errors
done

# The layout before channels: core/<sha>/ and core/latest-<os>.txt. Nothing
# reads them any more.
for LEGACY in $(s3 ls "$ROOT/" | awk '$1 == "PRE" { print $2 }' | grep -E '^[0-9a-f]{40}/$' || true); do
  echo "Deleting staging build of the old layout core/$LEGACY"
  s3 rm "$ROOT/$LEGACY" --recursive --only-show-errors
done
for os in windows macos linux; do
  s3 rm "$ROOT/latest-$os.txt" --only-show-errors 2>/dev/null || true
done
