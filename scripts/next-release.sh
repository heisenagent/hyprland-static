#!/bin/sh
# Print the tag and Debian revision the next release should use, as
# "TAG REVISION": "v0.57.0 1" for a new Hyprland version, "v0.56.2-3 3" for
# another package revision of one that's already released.  Existing
# release tags are read from the remote (default: origin).
set -eu
cd "$(dirname "$0")/.."
version=$(cat src/Hyprland/VERSION)
max=0
for tag in $(git ls-remote --tags "${1:-origin}" | awk '{print $2}' | grep -v '\^{}$' | sed 's|^refs/tags/||'); do
  case $tag in
    "v$version") [ "$max" -ge 1 ] || max=1 ;;
    "v$version"-*)
      n=${tag#"v$version"-}
      case $n in
        '' | *[!0-9]*) ;;
        *) [ "$n" -le "$max" ] || max=$n ;;
      esac
      ;;
  esac
done
next=$((max + 1))
if [ "$next" -eq 1 ]; then
  echo "v$version 1"
else
  echo "v$version-$next $next"
fi
