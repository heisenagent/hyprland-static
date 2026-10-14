import os
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

from scripts import release_notes as rn
from scripts.common import Submodule
from tests.conftest import GitRun

# What a trimmed build.ninja links, in the shape CMake writes it, with the
# archives STATIC_ARCHIVES expects ({deps} and {usr} filled in by `fake_root`).
LINKS = {
    ("Hyprland", "Hyprland"): [
        "libhyprland_lib.a",
        *(f"{{deps}}/lib{n}.a" for n in ["aquamarine", "hyprcursor", "hyprgraphics"]),
        *(f"{{deps}}/lib{n}.a" for n in ["hyprlang", "hyprutils"]),
        "{usr}/libglslang.a",
        "{usr}/libglslang-default-resource-limits.a",
        "{usr}/libSPIRV.a",
        "{usr}/liblcms2_fast_float.a",
        "{usr}/liblcms2_threaded.a",
        "{usr}/librt.a",
        "/usr/lib/x86_64-linux-gnu/libdrm.so",
    ],
    ("hyprctl/hyprctl", "hyprctl"): [
        "{deps}/libhyprutils.a",
        "{deps}/libhyprwire.a",
        "{usr}/librt.a",
    ],
    ("start/start-hyprland", "start-hyprland"): ["{deps}/libhyprutils.a"],
}


def fake_ninja() -> str:
    return "".join(
        f"build {target}: CXX_EXECUTABLE_LINKER__{rule}_Release {target}.o | libhyprland_lib.a\n"
        f"  FLAGS = -O3\n"
        f"  LINK_LIBRARIES = {'  '.join(libs)}\n"
        f"  OBJECT_DIR = CMakeFiles/{rule}.dir\n\n"
        for (target, rule), libs in LINKS.items()
    )


UBUNTU_OWNERS = {
    "libglslang.a": "glslang-dev",
    "libglslang-default-resource-limits.a": "glslang-dev",
    "libSPIRV.a": "glslang-dev",
    "liblcms2_fast_float.a": "liblcms2-dev",
    "liblcms2_threaded.a": "liblcms2-dev",
}


def write_archive(path: Path, empty: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"!<arch>\n" if empty else b"!<arch>\nmember data")


@pytest.fixture
def fake_root(tmp_path: Path) -> Path:
    """A checkout after ./build.sh: build.ninja, archives, VERSION, a Hyprland binary."""
    root = tmp_path / "repo"
    deps, usr = root / "deps/lib", tmp_path / "usr/lib"
    for name in ["aquamarine", "hyprcursor", "hyprgraphics", "hyprlang", "hyprutils", "hyprwire"]:
        write_archive(deps / f"lib{name}.a")
    for name in UBUNTU_OWNERS:
        write_archive(usr / name)
    write_archive(usr / "librt.a", empty=True)
    ninja = root / "build/Hyprland/build.ninja"
    ninja.parent.mkdir(parents=True)
    ninja.write_text(fake_ninja().format(deps=deps, usr=usr))
    (root / "src/Hyprland").mkdir(parents=True)
    (root / "src/Hyprland/VERSION").write_text("0.56.2\n")
    (root / "patches").mkdir()
    (root / "patches/Hyprland-fix.patch").write_text("")
    binary = root / "stage/opt/hyprland-static/bin/Hyprland"
    binary.parent.mkdir(parents=True)
    binary.write_text('#!/bin/sh\necho "Hyprland 0.56.2 built from branch  ($XDG_RUNTIME_DIR)"\n')
    binary.chmod(0o755)
    return root


@pytest.fixture
def fake_tools(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, ...]]:
    """Stand-ins for gcc, dpkg and dpkg-query; other commands run for real."""
    calls: list[tuple[str, ...]] = []
    real_run = rn.run

    def run(*cmd: str | Path, cwd: Path = rn.ROOT, env: dict[str, str] | None = None) -> str:
        args = tuple(str(c) for c in cmd)
        calls.append(args)
        match args:
            case ("gcc", "-dumpfullversion"):
                return "15.2.0"
            case ("dpkg", "-S", path):
                return f"{UBUNTU_OWNERS[Path(path).name]}: {path}"
            case ("dpkg-query", "-W", "-f=${Version}", package):
                return {"gcc-15": "15.2.0-16ubuntu1"}.get(package, f"{package}-version")
        return real_run(*cmd, cwd=cwd, env=env)

    monkeypatch.setattr(rn, "run", run)
    monkeypatch.setattr(rn, "submodules", lambda root: [])
    monkeypatch.setattr(rn, "distro_name", lambda: "Ubuntu 26.04.1 LTS")
    return calls


# --- Parsing the link commands ---


def test_link_archives(fake_root: Path) -> None:
    archives = rn.link_archives((fake_root / "build/Hyprland/build.ninja").read_text())
    assert set(archives) == set(rn.BINARIES)
    assert archives["Hyprland"][0] == "libhyprland_lib.a"
    assert [Path(p).name for p in archives["hyprctl"]] == [
        "libhyprutils.a",
        "libhyprwire.a",
        "librt.a",
    ]
    assert all(not p.endswith(".so") for p in archives["Hyprland"])


def test_link_archives_for_a_missing_target() -> None:
    assert rn.link_archives("") == {binary: [] for binary in rn.BINARIES}


def test_external_archives_drops_internal_and_empty(tmp_path: Path) -> None:
    write_archive(tmp_path / "libreal.a")
    write_archive(tmp_path / "librt.a", empty=True)
    paths = ["libhyprland_lib.a", str(tmp_path / "libreal.a"), str(tmp_path / "librt.a")]
    assert rn.external_archives(paths) == [str(tmp_path / "libreal.a")]


def test_check_static_archives_accepts_the_expected_set() -> None:
    actual = {b: [f"/x/{name}" for name in names] for b, names in rn.STATIC_ARCHIVES.items()}
    assert rn.check_static_archives(actual) == []


def test_check_static_archives_reports_added_and_dropped() -> None:
    actual = {b: [f"/x/{name}" for name in names] for b, names in rn.STATIC_ARCHIVES.items()}
    actual["Hyprland"] = [p for p in actual["Hyprland"] if not p.endswith("libSPIRV.a")]
    actual["hyprctl"].append("/x/libnew.a")
    assert rn.check_static_archives(actual) == [
        "Hyprland: no longer linked statically: libSPIRV.a",
        "hyprctl: newly linked statically: libnew.a",
    ]


def test_check_static_archives_with_a_binary_missing() -> None:
    problems = rn.check_static_archives({})
    assert problems[0].startswith("Hyprland: no longer linked statically: libSPIRV.a")
    assert len(problems) == len(rn.BINARIES)


# --- Looking things up ---


def test_upstream_tag(tmp_path: Path, git_repo: Callable[..., GitRun]) -> None:
    g = git_repo("lib", ["v1.0", "v1.1"])
    url = str(tmp_path / "upstream/lib")
    assert rn.upstream_tag(url, g("rev-parse", "v1.0^{commit}")) == "v1.0"
    assert rn.upstream_tag(url, g("rev-parse", "HEAD~2")) is None


def test_dpkg_helpers(fake_tools: list[tuple[str, ...]]) -> None:
    assert rn.dpkg_owner("/usr/lib/libglslang.a") == "glslang-dev"
    assert rn.dpkg_version("gcc-15") == "15.2.0-16ubuntu1"


def test_distro_name(tmp_path: Path) -> None:
    os_release = tmp_path / "os-release"
    os_release.write_text('NAME="Ubuntu"\nPRETTY_NAME="Ubuntu 26.04.1 LTS"\n\n')
    assert rn.distro_name(os_release) == "Ubuntu 26.04.1 LTS"
    os_release.write_text("NAME=Ubuntu\n")
    assert rn.distro_name(os_release) == "unknown"


def test_hyprland_version_output_gets_a_runtime_dir(fake_root: Path) -> None:
    out = rn.hyprland_version_output(fake_root / "stage/opt/hyprland-static/bin/Hyprland")
    assert out.startswith("Hyprland 0.56.2 built from branch  (/")


# --- Table rows ---


def test_source_rows(tmp_path: Path, git_repo: Callable[..., GitRun], fake_root: Path) -> None:
    mods = []
    for name, tags in [
        ("Hyprland", ["v0.56.2"]),
        ("hyprwire", ["v0.3.1"]),
        ("glaze", ["v7.9.1"]),
        ("hyprwayland-scanner", ["v0.4.6"]),
        ("unused", ["v1.0"]),
    ]:
        g = git_repo(name, tags)
        if name == "unused":
            g("checkout", "-q", "HEAD~1")  # untagged
        mods.append(
            Submodule(name, str(tmp_path / "upstream" / name), f"https://github.com/x/{name}.git")
        )
    archives = rn.link_archives((fake_root / "build/Hyprland/build.ninja").read_text())
    # Tags are looked up at each project's URL; use the local upstreams.
    local = [Submodule(m.name, m.path, m.path) for m in mods]
    rows = rn.source_rows(local, archives, Path("/"))
    commit = {m.name: rn.git("rev-parse", "HEAD", cwd=Path(m.path)) for m in mods}
    assert rows[0] == (
        f"| [Hyprland]({mods[0].path}) | v0.56.2 | `{commit['Hyprland'][:12]}` | "
        "the compositor itself | `Hyprland`, `hyprctl`, `start-hyprland` |"
    )
    assert rows[1].endswith("| static library | `hyprctl` |")
    assert rows[2].endswith("| header-only library, compiled in | `Hyprland`, `start-hyprland` |")
    assert rows[3].endswith("| code generator for the protocols (build tool) | (build only) |")
    assert "| (untagged) |" in rows[4]
    assert rows[4].endswith("|  | (not linked) |")


def test_ubuntu_rows(fake_root: Path, fake_tools: list[tuple[str, ...]]) -> None:
    raw = rn.link_archives((fake_root / "build/Hyprland/build.ninja").read_text())
    archives = {b: rn.external_archives(p) for b, p in raw.items()}
    assert rn.ubuntu_rows(archives, fake_root) == [
        "| `glslang-dev` | glslang-dev-version | libSPIRV.a, libglslang-default-resource-limits.a, "
        "libglslang.a | `Hyprland` |",
        "| `liblcms2-dev` | liblcms2-dev-version | liblcms2_fast_float.a, liblcms2_threaded.a | "
        "`Hyprland` |",
    ]


# --- Rendering ---


def sample_notes(**changes: object) -> rn.Notes:
    notes = rn.Notes(
        hyprland_version="0.56.2",
        revision="3",
        distro="Ubuntu 26.04.1 LTS",
        gcc="15.2.0",
        gcc_package="15.2.0-16ubuntu1",
        patches=["Hyprland-fix.patch"],
        version_output="Hyprland 0.56.2",
        source_rows=["| src row |"],
        ubuntu_rows=["| ubuntu row |"],
        compiled_in_rows=["| compiled-in row |"],
    )
    for key, value in changes.items():
        setattr(notes, key, value)
    return notes


def test_render() -> None:
    text = rn.render(sample_notes())
    assert text.startswith(
        "Hyprland **0.56.2** for **Ubuntu 26.04.1 LTS**, package version `0.56.2-3`.\n"
    )
    assert "sudo apt install ./hyprland-static_0.56.2-3_amd64.deb" in text
    for row in ["| src row |", "| ubuntu row |", "| compiled-in row |"]:
        assert row in text
    assert "GCC 15.2.0 (`gcc-15` 15.2.0-16ubuntu1)" in text
    assert "Local patches: `Hyprland-fix.patch`" in text
    assert "```\nHyprland 0.56.2\n```" in text


def test_render_without_ubuntu_archives_or_patches() -> None:
    text = rn.render(sample_notes(ubuntu_rows=[], patches=[]))
    assert "| (none) | | | |" in text
    assert "Local patches: none" in text


# --- Collecting and main ---


def test_collect(fake_root: Path, fake_tools: list[tuple[str, ...]]) -> None:
    notes = rn.collect("3", fake_root)
    assert notes.hyprland_version == "0.56.2"
    assert notes.revision == "3"
    assert notes.gcc == "15.2.0"
    assert notes.gcc_package == "15.2.0-16ubuntu1"
    assert notes.patches == ["Hyprland-fix.patch"]
    assert notes.version_output.startswith("Hyprland 0.56.2")
    assert [r.split(" | ")[0] for r in notes.ubuntu_rows] == ["| `glslang-dev`", "| `liblcms2-dev`"]
    assert notes.compiled_in_rows == [
        "| `hyprland-protocols` | hyprland-protocols-version | Hyprland protocol definitions |",
        "| `libwayland-dev` | libwayland-dev-version | core Wayland protocol definitions |",
    ]
    # Empty archives are never looked up.
    assert ("dpkg", "-S", str(fake_root.parent / "usr/lib/librt.a")) not in fake_tools


def test_collect_fails_when_the_static_dependencies_change(
    fake_root: Path, fake_tools: list[tuple[str, ...]]
) -> None:
    ninja = fake_root / "build/Hyprland/build.ninja"
    extra = fake_root / "deps/lib/libnewdep.a"
    write_archive(extra)
    ninja.write_text(ninja.read_text().replace("libhyprutils.a\n", f"libhyprutils.a  {extra}\n", 1))
    with pytest.raises(SystemExit, match=r"start-hyprland: newly linked statically: libnewdep\.a"):
        rn.collect("1", fake_root)


def test_main_writes_the_notes(
    fake_root: Path,
    fake_tools: list[tuple[str, ...]],
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DEB_REVISION", "7")
    out = tmp_path / "notes/release-notes.md"
    rn.main(["--out", str(out)], fake_root)
    assert capsys.readouterr().out == f"wrote {out}\n"
    assert "package version `0.56.2-7`" in out.read_text()


def test_main_defaults(
    fake_root: Path, fake_tools: list[tuple[str, ...]], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("DEB_REVISION", raising=False)
    rn.main([], fake_root)
    assert "package version `0.56.2-1`" in (fake_root / "out/release-notes.md").read_text()


def test_runs_as_a_module(tmp_path: Path) -> None:
    result = subprocess.run(
        ["python3", "-m", "scripts.release_notes", "--help"],
        cwd=rn.ROOT,
        capture_output=True,
        text=True,
        check=True,
        env={**os.environ, "PYTHONPATH": str(rn.ROOT)},
    )
    assert "Write release notes listing exactly what a build put into its binaries" in result.stdout
