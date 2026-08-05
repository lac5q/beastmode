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
git -C "$REPO" add artifact.txt scripts/public-artifact-guard
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

printf '%s\n' "safe again" > "$REPO/artifact.txt"
git -C "$REPO" add artifact.txt
git -C "$REPO" commit -qm "remove unsafe material"
if ! "$REPO/scripts/public-artifact-guard" >/dev/null 2>&1; then
  echo "public-artifact-guard rejected a clean current tree" >&2
  exit 1
fi
set +e
"$REPO/scripts/public-artifact-guard" --history >/dev/null 2>&1
rc=$?
set -e
if [ "$rc" -ne 1 ]; then
  echo "public-artifact-guard missed sensitive material in full history (got $rc)" >&2
  exit 1
fi
echo "public-artifact-guard scans complete history"

SHALLOW="$TMP/shallow"
git clone -q --depth 1 "file://$REPO" "$SHALLOW"
set +e
"$SHALLOW/scripts/public-artifact-guard" --history >/dev/null 2>&1
rc=$?
set -e
if [ "$rc" -ne 2 ]; then
  echo "public-artifact-guard did not fail closed in a shallow clone (got $rc)" >&2
  exit 1
fi
echo "public-artifact-guard refuses incomplete shallow history"

for material in \
  "$(printf 'github_%s_%024d' pat 0)" \
  "$(printf 'sk-%s-%024d' proj 0)" \
  "$(printf 'password=%024d' 0)"; do
  printf '%s\n' "$material" > "$REPO/artifact.txt"
  git -C "$REPO" add artifact.txt
  git -C "$REPO" commit -qm "credential form fixture"
  set +e
  "$REPO/scripts/public-artifact-guard" >/dev/null 2>&1
  rc=$?
  set -e
  if [ "$rc" -ne 1 ]; then
    echo "public-artifact-guard missed an expanded credential form (got $rc)" >&2
    exit 1
  fi
done
echo "public-artifact-guard rejects expanded credential forms"

BINARY_REPO="$TMP/binary-repo"
mkdir -p "$BINARY_REPO/scripts"
cp "$ROOT/scripts/public-artifact-guard" "$BINARY_REPO/scripts/public-artifact-guard"
chmod +x "$BINARY_REPO/scripts/public-artifact-guard"
git -C "$BINARY_REPO" init -q
git -C "$BINARY_REPO" config user.name "Beastmode Test"
git -C "$BINARY_REPO" config user.email "beastmode-test@example.invalid"
binary_material="$(printf 'gh%s_%024d' p 0)"
printf '\000%s\000' "$binary_material" > "$BINARY_REPO/binary.dat"
git -C "$BINARY_REPO" add binary.dat scripts/public-artifact-guard
git -C "$BINARY_REPO" commit -qm "binary fixture"
printf '%s\n' safe > "$BINARY_REPO/binary.dat"
git -C "$BINARY_REPO" add binary.dat
git -C "$BINARY_REPO" commit -qm "clean current tree"
set +e
"$BINARY_REPO/scripts/public-artifact-guard" --history >/dev/null 2>&1
rc=$?
set -e
if [ "$rc" -ne 1 ]; then
  echo "public-artifact-guard missed binary credential bytes in history (got $rc)" >&2
  exit 1
fi
echo "public-artifact-guard scans raw binary history"

NPM_REPO="$TMP/npm-repo"
mkdir -p "$NPM_REPO/scripts"
cp "$ROOT/scripts/public-artifact-guard" "$NPM_REPO/scripts/public-artifact-guard"
chmod +x "$NPM_REPO/scripts/public-artifact-guard"
git -C "$NPM_REPO" init -q
git -C "$NPM_REPO" config user.name "Beastmode Test"
git -C "$NPM_REPO" config user.email "beastmode-test@example.invalid"
npm_material="$(printf 'n%sm_%032d' p 0)"
printf '//registry.npmjs.org/:_authToken=%s\n' "$npm_material" > "$NPM_REPO/.npmrc"
git -C "$NPM_REPO" add .npmrc scripts/public-artifact-guard
git -C "$NPM_REPO" commit -qm "npm credential fixture"
set +e
"$NPM_REPO/scripts/public-artifact-guard" --history >/dev/null 2>&1
rc=$?
set -e
if [ "$rc" -ne 1 ]; then
  echo "public-artifact-guard missed npm credentials in full history (got $rc)" >&2
  exit 1
fi
echo "public-artifact-guard rejects npm credentials in full history"

blocked_name=".env"$'\n'"encoded"
printf '%s\n' safe > "$BINARY_REPO/$blocked_name"
git -C "$BINARY_REPO" add -- "$blocked_name"
git -C "$BINARY_REPO" commit -qm "encoded path fixture"
set +e
"$BINARY_REPO/scripts/public-artifact-guard" >/dev/null 2>&1
rc=$?
set -e
if [ "$rc" -ne 1 ]; then
  echo "public-artifact-guard missed a control-byte blocked filename (got $rc)" >&2
  exit 1
fi
echo "public-artifact-guard parses blocked paths with NUL-safe plumbing"

ARCHIVE="$TMP/generated.whl"
python3 - "$ARCHIVE" "$binary_material" <<'PY'
import sys
import zipfile

with zipfile.ZipFile(sys.argv[1], "w") as archive:
    archive.writestr("generated/only.txt", sys.argv[2])
PY
set +e
"$ROOT/scripts/public-artifact-guard" --artifact "$ARCHIVE" >/dev/null 2>&1
rc=$?
set -e
if [ "$rc" -ne 1 ]; then
  echo "public-artifact-guard missed generated-only credential material (got $rc)" >&2
  exit 1
fi
echo "public-artifact-guard scans generated distribution bytes"

NPM_ARCHIVE="$TMP/npm-credential.whl"
python3 - "$NPM_ARCHIVE" <<'PY'
import sys
import zipfile

with zipfile.ZipFile(sys.argv[1], "w") as archive:
    archive.writestr("package/.npmrc", "registry=https://registry.npmjs.org/")
PY
set +e
"$ROOT/scripts/public-artifact-guard" --artifact "$NPM_ARCHIVE" >/dev/null 2>&1
rc=$?
set -e
if [ "$rc" -ne 1 ]; then
  echo "public-artifact-guard missed a credential filename in an archive (got $rc)" >&2
  exit 1
fi
echo "public-artifact-guard rejects credential filenames in distributions"

NPM_TOKEN_ARCHIVE="$TMP/npm-token.whl"
python3 - "$NPM_TOKEN_ARCHIVE" "$npm_material" <<'PY'
import sys
import zipfile

with zipfile.ZipFile(sys.argv[1], "w") as archive:
    archive.writestr("package/config.txt", sys.argv[2])
PY
set +e
"$ROOT/scripts/public-artifact-guard" --artifact "$NPM_TOKEN_ARCHIVE" >/dev/null 2>&1
rc=$?
set -e
if [ "$rc" -ne 1 ]; then
  echo "public-artifact-guard missed npm token bytes in an archive (got $rc)" >&2
  exit 1
fi
echo "public-artifact-guard rejects npm token bytes in distributions"
