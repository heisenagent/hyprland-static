import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

from scripts import common
from tests.conftest import GitRun


def test_run_returns_stripped_stdout(tmp_path: Path) -> None:
    assert common.run("echo", "  hi  ", cwd=tmp_path) == "hi"


def test_run_passes_environment(tmp_path: Path) -> None:
    out = common.run("sh", "-c", "echo $X", cwd=tmp_path, env={"X": "set", "PATH": "/usr/bin:/bin"})
    assert out == "set"


def test_run_raises_on_failure(tmp_path: Path) -> None:
    with pytest.raises(subprocess.CalledProcessError):
        common.run("false", cwd=tmp_path)


def test_submodules_lists_hyprland_first(tmp_path: Path) -> None:
    common.git("init", "-q", cwd=tmp_path)
    for name, url in [
        ("zlib", "https://x/zlib.git"),
        ("Hyprland", "https://x/H.git"),
        ("aquamarine", "https://x/aq.git"),
    ]:
        common.git(
            "config", "-f", ".gitmodules", f"submodule.src/{name}.path", f"src/{name}", cwd=tmp_path
        )
        common.git("config", "-f", ".gitmodules", f"submodule.src/{name}.url", url, cwd=tmp_path)
    mods = common.submodules(tmp_path)
    assert [m.name for m in mods] == ["Hyprland", "aquamarine", "zlib"]
    assert mods[0] == common.Submodule(
        "Hyprland", "src/Hyprland", "https://x/H.git", "src/Hyprland"
    )


def test_remote_tags_peels_annotated_tags(tmp_path: Path, git_repo: Callable[..., GitRun]) -> None:
    g = git_repo("lib", ["v1.0", "2.0", "nightly"])
    tags = common.remote_tags(str(tmp_path / "upstream/lib"))
    assert set(tags) == {"v1.0", "2.0", "nightly"}
    # The annotated tag maps to its commit, not the tag object.
    assert tags["v1.0"] == g("rev-parse", "v1.0^{commit}")
    assert tags["2.0"] == g("rev-parse", "2.0")


def test_remote_tags_releases_only(tmp_path: Path, git_repo: Callable[..., GitRun]) -> None:
    git_repo("lib", ["v1.0", "nightly", "v2.0-rc1"])
    assert set(common.remote_tags(str(tmp_path / "upstream/lib"), releases_only=True)) == {"v1.0"}


@pytest.mark.parametrize(
    ("tag", "expected"), [("v0.15.1", (0, 15, 1)), ("1.49", (1, 49)), ("v7.9.10", (7, 9, 10))]
)
def test_version(tag: str, expected: tuple[int, ...]) -> None:
    assert common.version(tag) == expected


def test_version_sorts_numerically() -> None:
    assert max(["v0.9.3", "v0.15.1", "v0.10.0"], key=common.version) == "v0.15.1"


def test_version_rejects_non_release_tags() -> None:
    with pytest.raises(ValueError, match="not a release tag"):
        common.version("nightly")


def test_run_without_check_returns_output_of_a_failing_command(tmp_path: Path) -> None:
    assert common.run("sh", "-c", "echo out; exit 3", cwd=tmp_path, check=False) == "out"


def test_submodule_section_uses_its_key_or_path() -> None:
    assert common.Submodule("H", "src/H", "u", "custom").section == "submodule.custom"
    assert common.Submodule("H", "src/H", "u").section == "submodule.src/H"


def make_branches(git_repo: Callable[..., GitRun], branches: dict[str, str]) -> tuple[str, GitRun]:
    """A repo with release tags v1.0 and v2.0 (main is at v2.0) plus `branches` -> tag."""
    g = git_repo("lib", ["v1.0", "v2.0"])
    for branch, tag in branches.items():
        g("branch", branch, tag)
    return g("rev-parse", "v2.0^{commit}"), g


def test_branch_at_finds_the_one_release_branch(
    tmp_path: Path, git_repo: Callable[..., GitRun]
) -> None:
    # main (the default branch) is at v2.0 too, but doesn't count.
    commit, _ = make_branches(git_repo, {"v2.0-b": "v2.0", "v1.0-b": "v1.0"})
    assert common.branch_at(str(tmp_path / "upstream/lib"), commit) == "v2.0-b"


def test_branch_at_without_a_release_branch(
    tmp_path: Path, git_repo: Callable[..., GitRun]
) -> None:
    commit, _ = make_branches(git_repo, {"v1.0-b": "v1.0"})
    assert common.branch_at(str(tmp_path / "upstream/lib"), commit) is None


def test_branch_at_with_several_candidates_names_none(
    tmp_path: Path, git_repo: Callable[..., GitRun]
) -> None:
    commit, _ = make_branches(git_repo, {"v2.0-b": "v2.0", "stable": "v2.0"})
    assert common.branch_at(str(tmp_path / "upstream/lib"), commit) is None
