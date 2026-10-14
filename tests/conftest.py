"""Shared fixtures: isolated git configuration and small local git repos."""

import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

GitRun = Callable[..., str]


@pytest.fixture(autouse=True)
def isolated_git(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Keep the user's git config out, and allow file:// submodules."""
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(tmp_path / "gitconfig"))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("GIT_CONFIG_COUNT", "2")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "protocol.file.allow")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", "always")
    monkeypatch.setenv("GIT_CONFIG_KEY_1", "init.defaultBranch")
    monkeypatch.setenv("GIT_CONFIG_VALUE_1", "main")
    for who in ("AUTHOR", "COMMITTER"):
        monkeypatch.setenv(f"GIT_{who}_NAME", "Test")
        monkeypatch.setenv(f"GIT_{who}_EMAIL", "test@example.com")


def git_in(path: Path) -> GitRun:
    """A git runner for one directory."""

    def run(*args: str) -> str:
        return subprocess.run(
            ["git", *args], cwd=path, check=True, capture_output=True, text=True
        ).stdout.strip()

    return run


def make_upstream(path: Path, tags: list[str], files: dict[str, str] | None = None) -> GitRun:
    """A repo with one commit per tag (annotated tags for v*, lightweight otherwise).

    `files` are written before the first commit; each tag's commit also
    writes VERSION with that tag's version.
    """
    path.mkdir(parents=True)
    g = git_in(path)
    g("init", "-q")
    for name, content in (files or {}).items():
        (path / name).write_text(content)
    g("add", "-A")
    g("commit", "-q", "--allow-empty", "-m", "initial")
    for tag in tags:
        (path / "VERSION").write_text(tag.lstrip("v") + "\n")
        g("add", "VERSION")
        g("commit", "-q", "-m", f"release {tag}")
        if tag.startswith("v"):
            g("tag", "-a", tag, "-m", tag)
        else:
            g("tag", tag)
    return g


@pytest.fixture
def git_repo(tmp_path: Path) -> Callable[..., GitRun]:
    """Factory for upstream repos under tmp_path/upstream/<name>."""

    def factory(name: str, tags: list[str], files: dict[str, str] | None = None) -> GitRun:
        return make_upstream(tmp_path / "upstream" / name, tags, files)

    return factory
