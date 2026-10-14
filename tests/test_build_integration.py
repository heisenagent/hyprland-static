"""Checks against a real build: run after ./build.sh with `pytest -m build --no-cov`.

These compare the static dependencies Hyprland was actually linked with
(the linker commands ninja ran) against the declared list in
scripts/release_notes.py and against the release notes it writes.  If a new
Hyprland version adds or drops a static dependency, they fail.
"""

import shlex
from pathlib import Path

import pytest

from scripts import release_notes as rn
from scripts.common import ROOT, run

BUILD = ROOT / "build/Hyprland"
NINJA_TARGETS = {
    "Hyprland": "Hyprland",
    "hyprctl": "hyprctl/hyprctl",
    "start-hyprland": "start/start-hyprland",
}

pytestmark = [
    pytest.mark.build,
    pytest.mark.skipif(not (BUILD / "build.ninja").exists(), reason="needs ./build.sh first"),
]


def linked_archives(binary: str) -> set[str]:
    """Static archives in the binary's actual link command, by file name.

    `ninja -t commands` prints every command needed to build the target,
    ending with the link.  Hyprland's internal library and glibc's empty
    stubs are dropped, as in the release notes.
    """
    link = run("ninja", "-C", BUILD, "-t", "commands", NINJA_TARGETS[binary]).splitlines()[-1]
    archives = [arg for arg in shlex.split(link) if arg.endswith(".a")]
    absolute = [a for a in archives if a.startswith("/")]
    return {Path(a).name for a in rn.external_archives(absolute)}


@pytest.mark.parametrize("binary", rn.BINARIES)
def test_declared_static_archives_match_the_link_command(binary: str) -> None:
    actual = linked_archives(binary)
    expected = rn.STATIC_ARCHIVES[binary]
    assert actual == expected, (
        f"{binary} is now linked with {sorted(actual - expected)} and no longer with "
        f"{sorted(expected - actual)}: update STATIC_ARCHIVES in scripts/release_notes.py"
    )


@pytest.mark.parametrize("binary", rn.BINARIES)
def test_release_notes_parser_agrees_with_the_link_command(binary: str) -> None:
    parsed = rn.link_archives((BUILD / "build.ninja").read_text())[binary]
    assert {Path(p).name for p in rn.external_archives(parsed)} == linked_archives(binary)


def test_release_notes_list_every_static_dependency(tmp_path: Path) -> None:
    out = tmp_path / "notes.md"
    rn.main(["--out", str(out)])
    notes = out.read_text()
    source = notes.split("## Built from source")[1].split("## Ubuntu libraries")[0]
    ubuntu = notes.split("## Ubuntu libraries linked statically")[1].split("## Compiled in")[0]

    for binary in rn.BINARIES:
        for archive in linked_archives(binary):
            project = archive.removeprefix("lib").removesuffix(".a")
            built_here = (ROOT / "deps/lib" / archive).exists()
            if built_here:
                row = next(r for r in source.splitlines() if r.startswith(f"| [{project}]("))
                assert "| static library |" in row
                assert f"`{binary}`" in row, f"{project} row doesn't list {binary}: {row}"
            else:
                row = next((r for r in ubuntu.splitlines() if archive in r), None)
                assert row is not None, f"{archive} (in {binary}) missing from the Ubuntu table"
                assert f"`{binary}`" in row
    assert "(not linked)" not in source
