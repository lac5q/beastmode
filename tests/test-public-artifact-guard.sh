#!/usr/bin/env bash

set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
mkdir -p "$TMP/bin"
printf '#!/usr/bin/env bash\nexit 7\n' > "$TMP/bin/git"
chmod +x "$TMP/bin/git"

set +e
PATH="$TMP/bin:$PATH" "$ROOT/scripts/public-artifact-guard" >/dev/null 2>&1
rc=$?
set -e

if [ "$rc" -ne 2 ]; then
  echo "public-artifact-guard did not fail closed for scanner exit 7 (got $rc)" >&2
  exit 1
fi
echo "public-artifact-guard fails closed on scanner errors"

REPO="$TMP/repo"
mkdir -p "$REPO/scripts"
cp "$ROOT/scripts/public-artifact-guard" "$REPO/scripts/public-artifact-guard"
chmod +x "$REPO/scripts/public-artifact-guard"
git -C "$REPO" init -q
git -C "$REPO" config user.name "Beastmode Test"
git -C "$REPO" config user.email "beastmode-test@example.invalid"
printf '%s\n' "safe" > "$REPO/artifact.txt"
git -C "$REPO" add artifact.txt
git -C "$REPO" commit -qm "safe"
SAFE_COMMIT="$(git -C "$REPO" rev-parse HEAD)"

printf 'ghp_%024d\n' 0 > "$REPO/artifact.txt"
if ! "$REPO/scripts/public-artifact-guard" >/dev/null 2>&1; then
  echo "public-artifact-guard scanned mutable worktree content instead of HEAD" >&2
  exit 1
fi
echo "public-artifact-guard defaults to immutable HEAD content"

git -C "$REPO" add artifact.txt
git -C "$REPO" commit -qm "unsafe"
printf '%s\n' "safe again" > "$REPO/artifact.txt"
set +e
"$REPO/scripts/public-artifact-guard" >/dev/null 2>&1
rc=$?
set -e
if [ "$rc" -ne 1 ]; then
  echo "public-artifact-guard missed a secret committed at HEAD (got $rc)" >&2
  exit 1
fi
echo "public-artifact-guard rejects sensitive content in HEAD despite a clean-looking worktree"

if ! "$REPO/scripts/public-artifact-guard" --treeish "$SAFE_COMMIT" >/dev/null 2>&1; then
  echo "public-artifact-guard could not scan an explicit immutable commit" >&2
  exit 1
fi
echo "public-artifact-guard accepts an explicit immutable treeish"
