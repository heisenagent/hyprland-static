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
    assert mods[0] == common.Submodule("Hyprland", "src/Hyprland", "https://x/H.git")


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
