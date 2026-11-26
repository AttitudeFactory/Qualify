"""dev/code-graph-sync.py against a temp clone with a linked worktree and a stub `gh` (m-25129388).

Offline: the stub serves a release + assets from a temp dir and logs every call. The shared
store is the temp clone's own graphify-out/, never the developer's real one.
"""

from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "dev" / "code-graph-sync.py"
COMMIT = "c" * 40

STUB_GH = """import os, sys
d = os.environ["STUB_GH_DIR"]
with open(os.path.join(d, "calls.log"), "a") as fh:
    fh.write(" ".join(sys.argv[1:]) + "\\n")
endpoint = sys.argv[2]
if os.path.exists(os.path.join(d, "no-release")):
    sys.stderr.write("gh: Not Found (HTTP 404)\\n")
    sys.exit(1)
if endpoint.endswith("/releases/tags/code-graph"):
    sys.stdout.write(open(os.path.join(d, "release.json")).read())
elif "/releases/assets/" in endpoint:
    asset = os.path.join(d, "asset-" + endpoint.rsplit("/", 1)[1])
    sys.stdout.buffer.write(open(asset, "rb").read())
else:
    sys.exit(1)
"""


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True)


def _publish(stub: Path, commit: str, graph: bytes) -> None:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name, data in (("graph.json", graph), ("GRAPH_REPORT.md", b"# report\n")):
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
        evil = tarfile.TarInfo("../escape.txt")  # must be ignored by the installer
        evil.size = 1
        tar.addfile(evil, io.BytesIO(b"x"))
    meta = {"commit": commit, "built_at": "2026-11-26T11:17:00Z", "nodes": 2, "edges": 1}
    (stub / "asset-11").write_text(json.dumps(meta))
    (stub / "asset-12").write_bytes(buf.getvalue())
    release = {
        "assets": [{"id": 11, "name": "code-graph.json"}, {"id": 12, "name": "code-graph.tar.gz"}]
    }
    (stub / "release.json").write_text(json.dumps(release))


@pytest.fixture
def env(tmp_path: Path) -> dict[str, object]:
    if not shutil.which("git"):
        pytest.skip("git not available")
    main = tmp_path / "clone"
    main.mkdir()
    _git(main, "init", "-q", "-b", "main")
    _git(
        main,
        "-c",
        "user.email=t@t",
        "-c",
        "user.name=t",
        "commit",
        "-q",
        "--allow-empty",
        "-m",
        "init",
    )
    worktree = tmp_path / "wt"
    _git(main, "worktree", "add", "-q", "-b", "feature", str(worktree))

    stub = tmp_path / "stub"
    bin_dir = tmp_path / "bin"
    stub.mkdir()
    bin_dir.mkdir()
    gh = bin_dir / "gh"
    gh.write_text(f"#!{sys.executable}\n{STUB_GH}")
    gh.chmod(0o755)
    graphify = bin_dir / "graphify"
    graphify.write_text("#!/bin/sh\nexit 0\n")
    graphify.chmod(0o755)
    _publish(stub, COMMIT, b'{"nodes": [1, 2]}')

    # Only the stubs + git on PATH: git's own dir may also hold the real gh (Homebrew).
    (bin_dir / "git").symlink_to(shutil.which("git") or "/usr/bin/git")
    run_env = {
        "PATH": f"{bin_dir}{os.pathsep}/bin",
        "HOME": str(tmp_path),
        "STUB_GH_DIR": str(stub),
        "CODE_GRAPH_EXACT_PATH": "1",
    }
    return {"main": main, "wt": worktree, "stub": stub, "bin": bin_dir, "env": run_env}


def _run(env: dict[str, object], *args: str, stdin: str = "") -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=env["wt"],
        env=env["env"],
        input=stdin,
        capture_output=True,
        text=True,
        timeout=60,
    )


def _calls(env: dict[str, object]) -> list[str]:
    log = env["stub"] / "calls.log"
    return log.read_text().splitlines() if log.exists() else []


def test_first_run_installs_and_links_then_same_commit_downloads_nothing(env) -> None:
    store = env["main"].resolve() / "graphify-out"

    first = _run(env, "--now")
    assert first.returncode == 0, first.stderr
    assert "code graph installed" in first.stdout
    assert (store / "graph.json").read_bytes() == b'{"nodes": [1, 2]}'
    assert json.loads((store / ".code-graph-installed.json").read_text())["commit"] == COMMIT
    assert not (env["main"].parent / "escape.txt").exists()
    assert not (store.parent / "escape.txt").exists()
    for name in ("graph.json", "GRAPH_REPORT.md", ".graphify_labels.json"):
        link = env["wt"] / "graphify-out" / name
        assert link.is_symlink() and os.readlink(link) == str(store / name)
    assert (env["wt"] / "graphify-out" / "graph.json").read_bytes() == b'{"nodes": [1, 2]}'
    assert any("assets/12" in call for call in _calls(env))

    (env["stub"] / "calls.log").unlink()
    second = _run(env, "--now")
    assert second.returncode == 0, second.stderr
    assert "already up to date" in second.stdout
    assert not any("assets/12" in call for call in _calls(env))  # no tarball download


def test_regular_graph_in_worktree_is_left_alone(env) -> None:
    out = env["wt"] / "graphify-out"
    out.mkdir()
    (out / "graph.json").write_text("local graph")

    result = _run(env, "--now")
    assert result.returncode == 0, result.stderr
    assert not (out / "graph.json").is_symlink()
    assert (out / "graph.json").read_text() == "local graph"
    assert (out / "GRAPH_REPORT.md").is_symlink()


def test_missing_gh_exits_zero_with_one_hint_and_still_links(env) -> None:
    (env["bin"] / "gh").unlink()
    payload = json.dumps({"hook_event_name": "SessionStart", "cwd": str(env["wt"])})

    result = _run(env, stdin=payload)
    assert result.returncode == 0
    lines = result.stdout.strip().splitlines()
    assert len(lines) == 1 and "gh" in lines[0] and "brew install gh" in lines[0]
    assert (env["wt"] / "graphify-out" / "graph.json").is_symlink()


def test_missing_graphify_prints_the_pinned_install_command(env) -> None:
    (env["bin"] / "graphify").unlink()
    result = _run(env, stdin=json.dumps({"cwd": str(env["wt"])}))
    assert result.returncode == 0
    assert result.stdout.strip().startswith("code-graph: graphify is not installed")
    assert "uv tool install graphifyy==" in result.stdout


def test_no_release_yet_exits_zero_with_hint(env) -> None:
    (env["stub"] / "no-release").touch()
    result = _run(env, "--now")
    assert result.returncode == 0
    assert "just graph-build" in result.stdout
