"""Helpers shared by the scripts: running commands and reading submodules."""

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Release tags are just a version number: v0.15.1, 1.49.
RELEASE_TAG = re.compile(r"^v?(\d+(?:\.\d+)+)$")


def run(
    *cmd: str | Path, cwd: Path = ROOT, env: dict[str, str] | None = None, check: bool = True
) -> str:
    """Run a command and return its stripped stdout; raise if it fails (unless check=False)."""
    return subprocess.run(
        [str(c) for c in cmd], cwd=cwd, env=env, check=check, capture_output=True, text=True
    ).stdout.strip()


def git(*args: str, cwd: Path = ROOT, check: bool = True) -> str:
    return run("git", *args, cwd=cwd, check=check)


@dataclass(frozen=True)
class Submodule:
    name: str  # last path component, e.g. "Hyprland"
    path: str  # relative to the repository root, e.g. "src/Hyprland"
    url: str
    key: str = ""  # its section in .gitmodules ("submodule.<key>.path"); defaults to path

    @property
    def section(self) -> str:
        return f"submodule.{self.key or self.path}"


def submodules(root: Path = ROOT) -> list[Submodule]:
    """The repository's submodules, with Hyprland first, then by name."""
    out = git(
        "config", "-f", ".gitmodules", "--get-regexp", r"^submodule\..*\.(path|url)$", cwd=root
    )
    paths: dict[str, str] = {}
    urls: dict[str, str] = {}
    for line in out.splitlines():
        key, value = line.split(maxsplit=1)
        name, field = key.removeprefix("submodule.").rsplit(".", 1)
        (paths if field == "path" else urls)[name] = value
    mods = [Submodule(Path(paths[n]).name, paths[n], urls[n], n) for n in paths]
    return sorted(mods, key=lambda m: (m.name != "Hyprland", m.name.lower()))


def remote_tags(url: str, *, releases_only: bool = False) -> dict[str, str]:
    """{tag: commit} for a remote's tags, with annotated tags peeled."""
    tags: dict[str, str] = {}
    for line in git("ls-remote", "--tags", url).splitlines():
        sha, ref = line.split()
        peeled = ref.endswith("^{}")
        tag = ref.removeprefix("refs/tags/").removesuffix("^{}")
        if releases_only and not RELEASE_TAG.match(tag):
            continue
        if peeled or tag not in tags:
            tags[tag] = sha
    return tags


def branch_at(url: str, commit: str) -> str | None:
    """The upstream branch whose tip is exactly `commit`, if there is exactly one.

    The remote's default branch (e.g. main) doesn't count: it moves on, while
    a pin is a release.  Zero or several matches give None.  So a branch name
    is only ever taken verbatim from upstream, never derived from a version.
    """
    default = git("ls-remote", "--symref", url, "HEAD").split("\t")[0].removeprefix("ref: ")
    branches = [
        ref.removeprefix("refs/heads/")
        for sha, ref in (line.split() for line in git("ls-remote", "--heads", url).splitlines())
        if sha == commit and ref != default
    ]
    return branches[0] if len(branches) == 1 else None


def version(tag: str) -> tuple[int, ...]:
    """A release tag's version as numbers, for comparing: "v0.15.1" -> (0, 15, 1)."""
    m = RELEASE_TAG.match(tag)
    if not m:
        raise ValueError(f"not a release tag: {tag}")
    return tuple(int(x) for x in m.group(1).split("."))
