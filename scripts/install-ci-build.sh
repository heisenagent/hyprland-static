#!/bin/sh
# Install the .deb from the latest successful CI run of a pull request (or a
# branch), to test it before it's released:
#
#   scripts/install-ci-build.sh 12        # PR #12
#   scripts/install-ci-build.sh main      # latest build of main
#
# Needs the GitHub CLI (gh), logged in.  Run it from a clone of this repo.
# CI packages are versioned just below the next release (e.g. 0.56.2-3~ci57),
# so the release replaces them when you install it.
set -eu
[ $# -eq 1 ] || { echo "usage: $0 <PR number | branch>" >&2; exit 2; }

case $1 in
  *[!0-9]*) branch=$1 ;;
  *) branch=$(gh pr view "$1" --json headRefName --jq .headRefName) ;;
esac

run=$(gh run list --workflow CI --branch "$branch" --status success --limit 1 \
  --json databaseId --jq '.[0].databaseId // empty')
[ -n "$run" ] || { echo "No successful CI run for $branch" >&2; exit 1; }

# Download somewhere apt's _apt user can read.
dir=$(mktemp -d /tmp/hyprland-static-ci.XXXXXX)
chmod 755 "$dir"
trap 'rm -rf "$dir"' EXIT
gh run download "$run" --name hyprland-static-deb --dir "$dir"
chmod 644 "$dir"/*.deb

echo "Installing $(basename "$dir"/*.deb) from CI run $run ($branch)"
sudo apt install "$dir"/*.deb
