# hyprland-static

Builds a recent [Hyprland](https://github.com/hyprwm/Hyprland) for an Ubuntu
LTS release (currently **26.04**, which ships Hyprland 0.53) and packages it as
a `.deb`.

Hyprland's own libraries are newer than the LTS release has, so they're built
from source and **linked statically**: hyprutils, hyprlang, hyprwire,
hyprgraphics, hyprcursor and aquamarine.  Everything else (Mesa, libinput,
libdrm, Wayland, cairo, …) comes from Ubuntu and stays dynamic, so it keeps
getting Ubuntu's security and driver updates.

The package installs into `/opt/hyprland-static` and doesn't replace or
conflict with Ubuntu's `hyprland` package.  The login screen gets a
**Hyprland (static)** entry, and Ubuntu's Hyprland stays available as a
fallback session.

## Installing

Download the `.deb` from the [releases](../../releases) page and run:

    sudo apt install ./hyprland-static_*.deb

Then log out and pick **Hyprland (static)** at the login screen.  Remove it
with `sudo apt remove hyprland-static`.

The session launcher puts `/opt/hyprland-static/bin` first in `PATH`, so
`hyprctl` in scripts and keybindings matches the running Hyprland.

Not included: `hyprpm` and the plugin headers.  Plugins expect a dynamically
linked Hyprland.

## Building

    sudo apt install $(cat build-deps.txt)
    git submodule update --init --recursive
    ./build.sh

`./build.sh` builds everything, runs the tests and writes the `.deb` to
`out/`.  `./build.sh <step>...` runs single steps (see the end of
`build.sh`); logs go to `logs/`.

| Path | What |
|---|---|
| `src/` | upstream projects as git submodules, pinned to release tags |
| `patches/` | local fixes, applied by `build.sh` as `patches/<project>-*.patch` |
| `packaging/` | session launcher, login entry, Debian control template |
| `deps/`, `build/`, `stage/`, `out/`, `logs/` | build output (ignored by git) |

### Workarounds in build.sh

- **Static libraries:** each library's CMakeLists hardcodes `SHARED`;
  build.sh switches it to `STATIC` and adds the missing `Requires:` lines to
  the libraries' `.pc` files.
- **wayland-protocols:** Ubuntu 26.04's wayland-scanner (1.24) rejects some
  newer protocol files in `--strict` mode.  Only the optional C enum headers
  use it, so build.sh drops the flag.
- **Duplicate protocol tables:** aquamarine and Hyprland both define
  `wl_*_interface` / `xdg_*_interface` from the same XML.  build.sh makes
  aquamarine's copies local with objcopy (with shared libraries, Hyprland's
  copies win at runtime anyway).
- **GCC 15:** `patches/Hyprland-gcc15-ranges-starts-with.patch` replaces the
  one use of `std::ranges::starts_with` (GCC 16's libstdc++) with its
  definition in terms of `std::ranges::mismatch`.

## Tests

`./build.sh` runs:

- the libraries' own unit tests and Hyprland's unit tests, each in a
  separate Debug build (their test builds add sanitizers and coverage
  instrumentation that the release build mustn't have);
- checks on the staged binaries: version, no dynamically linked Hyprland
  libraries, nothing missing, and `Hyprland --verify-config` on
  `packaging/test.conf`.

Skipped, because build machines lack what they need: Hyprland's full
compositor tests (`hyprtester`, a GPU), hyprcursor's tests (an installed
hyprcursor theme) and aquamarine's `simpleWindow` (a running Wayland
compositor).

## Updating to a new Hyprland

1. Move the submodules to the new release tags:

       git -C src/Hyprland fetch --depth 1 origin tag v0.57.0
       git -C src/Hyprland checkout v0.57.0
       git -C src/Hyprland submodule update --init --recursive --depth 1

   Do the same for any library whose minimum version went up (see
   `src/Hyprland/CMakeLists.txt`).  glaze must stay within the major version
   Hyprland asks for.
2. Run `./build.sh`; fix or drop patches as needed.
3. Open a PR.  CI builds and tests it on `ubuntu-26.04`.

## Releases

Publishing a GitHub release builds the `.deb` and attaches it.  The tag must
be the Hyprland submodule's tag, optionally followed by `-N`:

| Tag | Package version |
|---|---|
| `v0.56.2` | `0.56.2-1` |
| `v0.56.2-2` | `0.56.2-2` |

Use `-N` to release packaging or build fixes for the same Hyprland version.
Any other tag fails the release build.

## CI

`.github/workflows/ci.yml` runs `./build.sh` on pushes to `main` and on pull
requests, on GitHub's `ubuntu-26.04` runner, and uploads the `.deb` as an
artifact.  Caches: the build-tool `.deb` files (keyed on `build-deps.txt`)
and ccache.

## License

The build scripts are BSD-3-Clause (see `LICENSE`).  The package bundles the
projects in `src/` under their own licenses (BSD-3-Clause for the Hyprland
projects, MIT for glaze); the package's
`/usr/share/doc/hyprland-static/copyright` includes them all.
