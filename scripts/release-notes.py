#!/usr/bin/env python3
"""Write release notes listing exactly what a build put into its binaries.

Run after `./build.sh` (the release workflow does).  The notes cover:

- the projects built from source in src/, with their upstream release tag
  and commit, and which binaries contain them;
- Ubuntu libraries linked statically (found in the build's link commands,
  with the Ubuntu package and version that provided them);
- protocol definitions from Ubuntu compiled into Hyprland;
- the build environment, local patches, and `Hyprland --version`.

Everything else is linked dynamically from Ubuntu and listed in the
package's Depends.
"""

import argparse
import os
import re
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build"
STAGE_BIN = ROOT / "stage/opt/hyprland-static/bin"
BINARIES = ["Hyprland", "hyprctl", "start-hyprland"]

# How each project in src/ ends up in the binaries.  Static libraries are
# matched to binaries from the link commands; COMPILED_INTO lists the rest.
HOW = {
    "Hyprland": "the compositor itself",
    "hyprutils": "static library",
    "hyprlang": "static library",
    "hyprwire": "static library",
    "hyprgraphics": "static library",
    "hyprcursor": "static library",
    "aquamarine": "static library",
    "glaze": "header-only library, compiled in",
    "wayland-protocols": "protocol definitions, compiled in",
    "hyprwayland-scanner": "code generator for the protocols (build tool)",
}
COMPILED_INTO = {
    "Hyprland": ["Hyprland", "hyprctl", "start-hyprland"],
    "glaze": ["Hyprland", "start-hyprland"],
    "wayland-protocols": ["Hyprland"],
    "hyprwayland-scanner": [],
}

# Ubuntu packages whose files are compiled into Hyprland at build time.
UBUNTU_COMPILED_IN = {
    "hyprland-protocols": "Hyprland protocol definitions",
    "libwayland-dev": "core Wayland protocol definitions",
}


def run(*cmd, cwd=ROOT, env=None):
    return subprocess.run(cmd, cwd=cwd, env=env, check=True, capture_output=True,
                          text=True).stdout.strip()


def submodules():
    out = run("git", "config", "-f", ".gitmodules", "--get-regexp", r"^submodule\..*\.(path|url)$")
    paths, urls = {}, {}
    for line in out.splitlines():
        key, value = line.split(maxsplit=1)
        name, field = key[len("submodule."):].rsplit(".", 1)
        (paths if field == "path" else urls)[name] = value
    return [(Path(paths[n]).name, paths[n], urls[n]) for n in paths]


def upstream_tag(url, commit):
    """The upstream tag for a commit (checkouts have no tags in CI)."""
    best = None
    for line in run("git", "ls-remote", "--tags", url).splitlines():
        sha, ref = line.split()
        if sha == commit:
            tag = ref[len("refs/tags/"):].removesuffix("^{}")
            if best is None or ref.endswith("^{}"):
                best = tag
    return best


def link_archives():
    """{binary: [static archive paths]} from the Hyprland build's link commands."""
    ninja = (BUILD / "Hyprland/build.ninja").read_text()
    result = {}
    for binary in BINARIES:
        m = re.search(rf"^build (?:\S*/)?{re.escape(binary)}: CXX_EXECUTABLE_LINKER.*?\n((?:  .*\n)+)",
                      ninja, re.M)
        libs = re.search(r"LINK_LIBRARIES = (.*)", m.group(1)) if m else None
        archives = re.findall(r"(\S+\.a)\b", libs.group(1)) if libs else []
        result[binary] = [a for a in archives if a.startswith("/")]
    return result


def dpkg_owner(path):
    pkg = run("dpkg", "-S", path).split(":")[0]
    return pkg, run("dpkg-query", "-W", "-f=${Version}", pkg)


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--revision", default=os.environ.get("DEB_REVISION", "1"),
                        help="Debian revision of the package (default: $DEB_REVISION or 1)")
    parser.add_argument("--out", type=Path, default=ROOT / "out/release-notes.md")
    args = parser.parse_args()

    hyprland_version = (ROOT / "src/Hyprland/VERSION").read_text().strip()
    archives = link_archives()

    # Which binaries contain each static library built from src/.
    in_binaries = {}
    for binary, paths in archives.items():
        for path in paths:
            m = re.search(r"/deps/lib/lib(.+)\.a$", path)
            if m:
                in_binaries.setdefault(m.group(1), []).append(f"`{binary}`")

    rows = []
    for name, path, url in sorted(submodules(), key=lambda m: (m[0] != "Hyprland", m[0].lower())):
        commit = run("git", "-C", path, "rev-parse", "HEAD")
        tag = upstream_tag(url, commit) or "(untagged)"
        how = HOW.get(name, "")
        where = ", ".join(in_binaries.get(name, []))
        if name in COMPILED_INTO:
            where = ", ".join(f"`{b}`" for b in COMPILED_INTO[name]) or "(build only)"
        elif how.startswith("static library") and not where:
            how += " (not linked)"
        project = url.removesuffix(".git")
        rows.append(f"| [{name}]({project}) | {tag} | `{commit[:12]}` | {how} | {where} |")

    # Ubuntu archives linked statically (skip glibc's empty compatibility
    # stubs such as librt.a, which contain no code).
    ubuntu = {}
    for binary, paths in archives.items():
        for path in paths:
            if path.startswith(str(ROOT)) or os.path.getsize(path) <= 8:
                continue
            pkg, version = dpkg_owner(path)
            entry = ubuntu.setdefault((pkg, version), {"libs": set(), "bins": set()})
            entry["libs"].add(Path(path).name)
            entry["bins"].add(f"`{binary}`")
    ubuntu_rows = [
        f"| `{pkg}` | {version} | {', '.join(sorted(e['libs']))} | {', '.join(sorted(e['bins']))} |"
        for (pkg, version), e in sorted(ubuntu.items())
    ]

    compiled_in_rows = []
    for pkg, what in UBUNTU_COMPILED_IN.items():
        version = run("dpkg-query", "-W", "-f=${Version}", pkg)
        compiled_in_rows.append(f"| `{pkg}` | {version} | {what} |")

    os_release = dict(
        line.split("=", 1) for line in Path("/etc/os-release").read_text().splitlines() if "=" in line
    )
    distro = os_release.get("PRETTY_NAME", "?").strip('"')
    gcc = run("gcc", "-dumpfullversion")
    gcc_pkg = run("dpkg-query", "-W", "-f=${Version}", f"gcc-{gcc.split('.')[0]}")
    patches = sorted(p.name for p in (ROOT / "patches").glob("*.patch"))

    with tempfile.TemporaryDirectory() as runtime:
        version_output = run(str(STAGE_BIN / "Hyprland"), "--version",
                             env=dict(os.environ, XDG_RUNTIME_DIR=runtime))

    deb = f"hyprland-static_{hyprland_version}-{args.revision}_amd64.deb"
    notes = f"""Hyprland **{hyprland_version}** for **{distro}**, package version `{hyprland_version}-{args.revision}`.

## Install

    sudo apt install ./{deb}

Then pick **Hyprland (static)** at the login screen.  It installs into
`/opt/hyprland-static`, next to Ubuntu's `hyprland` package.

## Built from source

| Project | Version | Commit | How it's included | In |
|---|---|---|---|---|
{chr(10).join(rows)}

## Ubuntu libraries linked statically

| Ubuntu package | Version | Archives | In |
|---|---|---|---|
{chr(10).join(ubuntu_rows) or "| (none) | | | |"}

## Compiled in from Ubuntu packages

| Ubuntu package | Version | What |
|---|---|---|
{chr(10).join(compiled_in_rows)}

Everything else (Mesa, libinput, libdrm, Wayland, cairo, …) is linked
dynamically from Ubuntu; see the package's `Depends`.

## Build

- {distro}, GCC {gcc} (`gcc-{gcc.split('.')[0]}` {gcc_pkg})
- Local patches: {", ".join(f"`{p}`" for p in patches) or "none"}

<details><summary><code>Hyprland --version</code></summary>

```
{version_output}
```

"system has unknown" is expected: Hyprland looks for separately installed
copies of its libraries, but this build has them built in.

</details>
"""
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(notes)
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
