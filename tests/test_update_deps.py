import shutil
from collections.abc import Callable
from pathlib import Path

import pytest

from scripts import update_deps
from scripts.common import ROOT
from tests.conftest import GitRun, git_in

GLAZE_CMAKE = "find_package(glaze 7...<8 QUIET)\n"


def test_glaze_majors(tmp_path: Path) -> None:
    (tmp_path / "src/Hyprland").mkdir(parents=True)
    (tmp_path / "src/Hyprland/CMakeLists.txt").write_text(GLAZE_CMAKE)
    assert update_deps.glaze_majors(tmp_path) == range(7, 8)


def test_glaze_majors_without_a_limit(tmp_path: Path) -> None:
    (tmp_path / "src/Hyprland").mkdir(parents=True)
    (tmp_path / "src/Hyprland/CMakeLists.txt").write_text("find_package(glaze QUIET)\n")
    assert update_deps.glaze_majors(tmp_path) is None


def test_newest_release_picks_highest_version(tmp_path: Path) -> None:
    tags = {"v0.9.3": "a", "v0.15.1": "b", "v0.10.0": "c"}
    assert update_deps.newest_release("aquamarine", tags, tmp_path) == "v0.15.1"


def test_newest_release_keeps_glaze_within_hyprlands_limit(tmp_path: Path) -> None:
    (tmp_path / "src/Hyprland").mkdir(parents=True)
    (tmp_path / "src/Hyprland/CMakeLists.txt").write_text(GLAZE_CMAKE)
    tags = {"v7.9.1": "a", "v9.0.0": "b", "v7.10.0": "c", "v6.0.0": "d"}
    assert update_deps.newest_release("glaze", tags, tmp_path) == "v7.10.0"


def test_newest_release_without_tags(tmp_path: Path) -> None:
    assert update_deps.newest_release("hyprutils", {}, tmp_path) is None


@pytest.mark.parametrize(
    ("url", "link"),
    [
        (
            "https://github.com/hyprwm/aquamarine.git",
            "https://github.com/hyprwm/aquamarine/releases/tag/v1",
        ),
        (
            "https://gitlab.freedesktop.org/wayland/wayland-protocols.git",
            "https://gitlab.freedesktop.org/wayland/wayland-protocols/-/tags/v1",
        ),
        # Only the host counts, not "github.com" elsewhere in the URL.
        (
            "https://example.org/github.com/x.git",
            "https://example.org/github.com/x/-/tags/v1",
        ),
        (
            "https://github.com.example.org/x.git",
            "https://github.com.example.org/x/-/tags/v1",
        ),
    ],
)
def test_release_link(url: str, link: str) -> None:
    assert update_deps.release_link(url, "v1") == link


def test_write_pr_files(tmp_path: Path) -> None:
    updates = [
        update_deps.Update(
            "Hyprland", "https://github.com/hyprwm/Hyprland.git", "v0.56.2", "v0.57.0"
        ),
        update_deps.Update(
            "glaze", "https://github.com/stephenberry/glaze.git", "v7.9.1", "v7.9.2"
        ),
    ]
    update_deps.write_pr_files(updates, "v0.57.0", tmp_path)
    assert (tmp_path / "title.txt").read_text() == "Update Hyprland to v0.57.0, glaze to v7.9.2\n"
    summary = (tmp_path / "summary.md").read_text()
    assert (
        "| Hyprland | v0.56.2 | "
        "[v0.57.0](https://github.com/hyprwm/Hyprland/releases/tag/v0.57.0) |" in summary
    )
    assert "git tag v0.57.0 origin/main && git push origin v0.57.0" in summary
    assert (tmp_path / "commit.txt").read_text().splitlines()[2:] == [
        "- Hyprland: v0.56.2 -> v0.57.0",
        "- glaze: v7.9.1 -> v7.9.2",
    ]


# --- End to end, with a fake superproject and local "upstream" repos ---


def make_superproject(
    tmp_path: Path, git_repo: Callable[..., GitRun], pins: dict[str, tuple[list[str], str]]
) -> Path:
    """A repo like this one: submodules in src/ pinned to `pins[name][1]`.

    Each upstream gets the tags `pins[name][0]`.  Hyprland, which every
    superproject has (already at its newest release unless pinned), also
    gets the glaze limit in its CMakeLists.  The superproject's "origin" is
    a bare repo with no tags, for scripts/next-release.sh.
    """
    pins = {"Hyprland": (["v0.1.0"], "v0.1.0"), **pins}
    root = tmp_path / "super"
    root.mkdir()
    g = git_in(root)
    g("init", "-q")
    for name, (tags, pin) in pins.items():
        files = {"CMakeLists.txt": GLAZE_CMAKE} if name == "Hyprland" else None
        git_repo(name, tags, files)
        g("submodule", "add", "-q", str(tmp_path / "upstream" / name), f"src/{name}")
        git_in(root / "src" / name)("checkout", "-q", pin)
    (root / "scripts").mkdir()
    shutil.copy(ROOT / "scripts/next-release.sh", root / "scripts/next-release.sh")
    g("add", "-A")
    g("commit", "-q", "-m", "pins")
    git_in(tmp_path)("init", "-q", "--bare", "origin.git")
    g("remote", "add", "origin", str(tmp_path / "origin.git"))
    return root


def head_tag(root: Path, name: str) -> str:
    return git_in(root / "src" / name)("describe", "--tags", "--exact-match")


def test_main_moves_submodules_to_their_newest_releases(
    tmp_path: Path, git_repo: Callable[..., GitRun], capsys: pytest.CaptureFixture[str]
) -> None:
    root = make_superproject(
        tmp_path,
        git_repo,
        {
            "Hyprland": (["v0.1.0", "v0.2.0"], "v0.1.0"),
            "glaze": (["v7.0.0", "v7.1.0", "v8.0.0"], "v7.0.0"),
            "hyprutils": (["v1.0", "v1.1", "nightly"], "v1.1"),
        },
    )
    out = tmp_path / "out"
    update_deps.main(["--out", str(out)], root)

    captured = capsys.readouterr()
    assert captured.out == "changed=true\n"
    assert "Hyprland: v0.1.0 -> v0.2.0" in captured.err
    assert "glaze: v7.0.0 -> v7.1.0" in captured.err
    assert "hyprutils: v1.1 is the latest release" in captured.err
    assert head_tag(root, "Hyprland") == "v0.2.0"
    assert head_tag(root, "glaze") == "v7.1.0"  # not v8.0.0: Hyprland wants 7.x
    assert (out / "title.txt").read_text() == "Update Hyprland to v0.2.0, glaze to v7.1.0\n"
    # The new Hyprland version has no release yet, so it gets revision 1.
    assert "pushing the tag **`v0.2.0`**" in (out / "summary.md").read_text()


def test_main_reports_no_changes(
    tmp_path: Path, git_repo: Callable[..., GitRun], capsys: pytest.CaptureFixture[str]
) -> None:
    root = make_superproject(tmp_path, git_repo, {"hyprutils": (["v1.0", "v1.1"], "v1.1")})
    update_deps.main(["--out", str(tmp_path / "out")], root)
    assert capsys.readouterr().out == "changed=false\n"
    assert not (tmp_path / "out/title.txt").exists()


def test_main_names_an_untagged_pin_by_commit(
    tmp_path: Path, git_repo: Callable[..., GitRun], capsys: pytest.CaptureFixture[str]
) -> None:
    root = make_superproject(tmp_path, git_repo, {"hyprutils": (["v1.0", "v1.1"], "v1.0")})
    sub = git_in(root / "src/hyprutils")
    sub("checkout", "-q", "HEAD~1")  # the "initial" commit, not a release
    untagged = sub("rev-parse", "HEAD")[:12]
    update_deps.main(["--out", str(tmp_path / "out")], root)
    assert f"hyprutils: {untagged} -> v1.1" in capsys.readouterr().err


def test_main_skips_projects_without_release_tags(
    tmp_path: Path, git_repo: Callable[..., GitRun], capsys: pytest.CaptureFixture[str]
) -> None:
    root = make_superproject(tmp_path, git_repo, {"tool": (["nightly"], "nightly")})
    update_deps.main(["--out", str(tmp_path / "out")], root)
    assert "tool: no release tags found, skipping" in capsys.readouterr().err


def test_main_refuses_a_dirty_submodule(tmp_path: Path, git_repo: Callable[..., GitRun]) -> None:
    root = make_superproject(tmp_path, git_repo, {"hyprutils": (["v1.0", "v1.1"], "v1.0")})
    (root / "src/hyprutils/VERSION").write_text("local change\n")
    with pytest.raises(SystemExit, match="src/hyprutils has local changes"):
        update_deps.main(["--out", str(tmp_path / "out")], root)


def gitmodules_branch(root: Path) -> str:
    return git_in(root)(
        "config", "-f", ".gitmodules", "--default", "", "--get", "submodule.src/Hyprland.branch"
    )


def test_main_records_hyprlands_release_branch(
    tmp_path: Path, git_repo: Callable[..., GitRun], capsys: pytest.CaptureFixture[str]
) -> None:
    root = make_superproject(tmp_path, git_repo, {"Hyprland": (["v0.1.0", "v0.2.0"], "v0.1.0")})
    # Upstream's main also points at v0.2.0, but as the default branch it doesn't count.
    git_in(tmp_path / "upstream/Hyprland")("branch", "v0.2.0-b", "v0.2.0")
    update_deps.main(["--out", str(tmp_path / "out")], root)
    assert gitmodules_branch(root) == "v0.2.0-b"
    assert "Hyprland: release branch v0.2.0-b" in capsys.readouterr().err


def test_main_removes_a_stale_release_branch(
    tmp_path: Path, git_repo: Callable[..., GitRun], capsys: pytest.CaptureFixture[str]
) -> None:
    root = make_superproject(tmp_path, git_repo, {"Hyprland": (["v0.1.0", "v0.2.0"], "v0.1.0")})
    git_in(root)("config", "-f", ".gitmodules", "submodule.src/Hyprland.branch", "v0.1.0-b")
    update_deps.main(["--out", str(tmp_path / "out")], root)
    assert gitmodules_branch(root) == ""
    assert "Hyprland: no unique release branch at" in capsys.readouterr().err
