#!/usr/bin/env python3
"""Move each submodule in src/ to its newest upstream release tag.

Release tags are tags that are just a version number (v0.15.1, 1.49).
Hyprland is updated first, because its CMakeLists limits the others: glaze
must stay within the major versions Hyprland accepts (find_package(glaze
7...<8)).

Writes a PR title, a Markdown summary and a commit message into --out, and
prints "changed=true" or "changed=false" (for $GITHUB_OUTPUT).  Refuses to
touch a submodule with local changes, which build.sh makes while building
(run it on a clean checkout, as CI does).
"""

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RELEASE_TAG = re.compile(r"^v?(\d+(?:\.\d+)+)$")


def git(*args, cwd=ROOT):
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout.strip()


def submodules():
    """(name, path, url) for each submodule, with Hyprland first."""
    paths, urls = {}, {}
    out = git("config", "-f", ".gitmodules", "--get-regexp", r"^submodule\..*\.(path|url)$")
    for line in out.splitlines():
        key, value = line.split(maxsplit=1)
        name, field = key[len("submodule."):].rsplit(".", 1)
        (paths if field == "path" else urls)[name] = value
    mods = [(Path(paths[n]).name, paths[n], urls[n]) for n in paths]
    return sorted(mods, key=lambda m: (m[0] != "Hyprland", m[0].lower()))


def release_tags(url):
    """{tag: commit} for the remote's release tags (annotated tags peeled)."""
    tags = {}
    for line in git("ls-remote", "--tags", url).splitlines():
        sha, ref = line.split()
        tag = ref[len("refs/tags/"):]
        peeled = tag.endswith("^{}")
        tag = tag.removesuffix("^{}")
        if RELEASE_TAG.match(tag) and (peeled or tag not in tags):
            tags[tag] = sha
    return tags


def version(tag):
    return tuple(int(x) for x in RELEASE_TAG.match(tag).group(1).split("."))


def glaze_majors():
    """The glaze major versions Hyprland accepts, as range(lo, hi)."""
    cmake = (ROOT / "src/Hyprland/CMakeLists.txt").read_text()
    m = re.search(r"find_package\(glaze\s+(\d+)\.\.\.<(\d+)", cmake)
    return range(int(m.group(1)), int(m.group(2))) if m else None


def release_link(url, tag):
    base = url.removesuffix(".git")
    if "github.com" in base:
        return f"{base}/releases/tag/{tag}"
    return f"{base}/-/tags/{tag}"


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", type=Path, required=True,
                        help="directory for title.txt, summary.md and commit.txt")
    args = parser.parse_args()

    updates = []  # (name, url, old tag, new tag)
    for name, path, url in submodules():
        sub = ROOT / path
        if git("status", "--porcelain", cwd=sub):
            sys.exit(f"{path} has local changes; run this on a clean checkout")
        tags = release_tags(url)
        candidates = list(tags)
        if name == "glaze":
            majors = glaze_majors()
            if majors:
                candidates = [t for t in candidates if version(t)[0] in majors]
        if not candidates:
            print(f"{name}: no release tags found, skipping", file=sys.stderr)
            continue
        latest = max(candidates, key=version)
        head = git("rev-parse", "HEAD", cwd=sub)
        current = next((t for t, sha in tags.items() if sha == head), head[:12])
        if tags[latest] == head:
            print(f"{name}: {current} is the latest release", file=sys.stderr)
            continue
        print(f"{name}: {current} -> {latest}", file=sys.stderr)
        git("fetch", "-q", "--depth", "1", "origin", f"refs/tags/{latest}:refs/tags/{latest}", cwd=sub)
        git("-c", "advice.detachedHead=false", "checkout", "-q", latest, cwd=sub)
        if name == "Hyprland":
            git("submodule", "update", "-q", "--init", "--recursive", "--depth", "1", cwd=sub)
        updates.append((name, url, current, latest))

    args.out.mkdir(parents=True, exist_ok=True)
    if not updates:
        print("changed=false")
        return

    next_tag = subprocess.run(
        [ROOT / "scripts/next-release.sh"], check=True, capture_output=True, text=True
    ).stdout.split()[0]
    title = "Update " + ", ".join(f"{n} to {new}" for n, _, _, new in updates)
    rows = "\n".join(
        f"| {n} | {old} | [{new}]({release_link(url, new)}) |" for n, url, old, new in updates
    )
    summary = f"""Upstream released new versions:

| Project | From | To |
|---|---|---|
{rows}

CI builds and tests this PR; its `.deb` (an artifact of the CI run) can be
installed for testing with `scripts/install-ci-build.sh <PR number>`.

After merging, release it by pushing the tag **`{next_tag}`**:

    git fetch origin && git tag {next_tag} origin/main && git push origin {next_tag}

That publishes a pre-release with the `.deb`; promote it to a full release
once it works for you.
"""
    (args.out / "title.txt").write_text(title + "\n")
    (args.out / "summary.md").write_text(summary)
    (args.out / "commit.txt").write_text(
        title + "\n\n" + "\n".join(f"- {n}: {old} -> {new}" for n, _, old, new in updates) + "\n"
    )
    print("changed=true")


if __name__ == "__main__":
    main()
