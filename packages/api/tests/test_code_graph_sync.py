"""dev/code-graph-sync.py against a temp clone with a linked worktree and a stub `gh` (m-25129388).

Offline and hermetic: PATH holds only a temp bin dir (stub gh, stub graphify, a link to git),
never a system dir — ubuntu-latest ships a real `gh` in /usr/bin. The stub serves a release
and its assets from a temp dir and logs every call. The shared store is the temp clone's own
graphify-out/, never the developer's real one. Those end-to-end tests need shebang stubs and
symlinks, so they run on POSIX only; the Windows fallbacks (lock, hardlink/copy, interpreter
choice) have unit tests below that run on any OS (m-25129418).
"""

from __future__ import annotations

import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
import time
import types
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "dev" / "code-graph-sync.py"
COMMIT = "c" * 40
BUILT_AT = "2026-11-26T11:17:00Z"
posix_only = pytest.mark.skipif(sys.platform == "win32", reason="shebang stubs and symlinks")

STUB_GH = """import os, sys, time
d = os.environ["STUB_GH_DIR"]
with open(os.path.join(d, "calls.log"), "a") as fh:
    fh.write(" ".join(sys.argv[1:]) + "\\n")
endpoint = sys.argv[2]
if os.path.exists(os.path.join(d, "no-release")):
    sys.stderr.write("gh: Not Found (HTTP 404)\\n")
    sys.exit(1)
if endpoint.endswith("/releases/tags/code-graph"):
    time.sleep(float(os.environ.get("STUB_GH_SLEEP", "0")))  # the first call of a sync
    sys.stdout.write(open(os.path.join(d, "release.json")).read())
elif "/releases/assets/" in endpoint:
    asset = os.path.join(d, "asset-" + endpoint.rsplit("/", 1)[1])
    sys.stdout.buffer.write(open(asset, "rb").read())
else:
    sys.exit(1)
"""


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True)


def _member(tar: tarfile.TarFile, name: str, data: bytes) -> None:
    info = tarfile.TarInfo(name)
    info.size = len(data)
    tar.addfile(info, io.BytesIO(data))


def _publish(stub: Path, built_at: str = BUILT_AT, graph: bytes = b'{"nodes": [1, 2]}') -> dict:
    meta = {"commit": COMMIT, "built_at": built_at, "nodes": 2, "edges": 1}
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        _member(tar, "code-graph.json", json.dumps(meta).encode())
        _member(tar, "graph.json", graph)
        _member(tar, "GRAPH_REPORT.md", b"# report\n")
        # Hostile members the installer must ignore.
        _member(tar, "../escape.txt", b"x")
        sym = tarfile.TarInfo(".graphify_labels.json")
        sym.type, sym.linkname = tarfile.SYMTYPE, "/etc/passwd"
        tar.addfile(sym)
        hard = tarfile.TarInfo("GRAPH_REPORT.md")
        hard.type, hard.linkname = tarfile.LNKTYPE, "graph.json"
        tar.addfile(hard)
    (stub / "asset-11").write_text(json.dumps(meta))
    (stub / "asset-12").write_bytes(buf.getvalue())
    release = {
        "assets": [{"id": 11, "name": "code-graph.json"}, {"id": 12, "name": "code-graph.tar.gz"}]
    }
    (stub / "release.json").write_text(json.dumps(release))
    return meta


@pytest.fixture
def env(tmp_path: Path) -> dict:
    if sys.platform == "win32":
        pytest.skip("shebang stubs and symlinks: POSIX only (unit tests below cover Windows)")
    git = shutil.which("git")
    if not git:
        pytest.skip("git not available")
    main = tmp_path / "clone"
    main.mkdir()
    _git(main, "init", "-q", "-b", "main")
    _git(main, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "--allow-empty",
         "-m", "init")  # fmt: skip
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
    (bin_dir / "git").symlink_to(git)  # the only real tool the script needs
    _publish(stub)

    run_env = {
        "PATH": str(bin_dir),
        "HOME": str(tmp_path),
        "STUB_GH_DIR": str(stub),
        "CODE_GRAPH_EXACT_PATH": "1",
    }
    store = main.resolve() / "graphify-out"
    return {"main": main, "wt": worktree, "stub": stub, "bin": bin_dir, "env": run_env,
            "store": store}  # fmt: skip


def _run(env: dict, *args: str, stdin: str = "") -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=env["wt"],
        env=env["env"],
        input=stdin,
        capture_output=True,
        text=True,
        timeout=60,
    )


def _calls(env: dict) -> list[str]:
    log = env["stub"] / "calls.log"
    return log.read_text().splitlines() if log.exists() else []


def _tarball_downloads(env: dict) -> int:
    return sum("assets/12" in call for call in _calls(env))


def test_first_run_installs_and_links_then_same_build_downloads_nothing(env) -> None:
    store = env["store"]

    first = _run(env, "--now")
    assert first.returncode == 0, first.stderr
    assert "code graph installed" in first.stdout
    assert (store / "graph.json").read_bytes() == b'{"nodes": [1, 2]}'
    marker = json.loads((store / ".code-graph-installed.json").read_text())
    assert marker["installed"] == {"commit": COMMIT, "built_at": BUILT_AT, "nodes": 2, "edges": 1}
    for name in ("graph.json", "GRAPH_REPORT.md", ".graphify_labels.json"):
        link = env["wt"] / "graphify-out" / name
        assert link.is_symlink() and Path(link.readlink()) == store / name
    assert (env["wt"] / "graphify-out" / "graph.json").read_bytes() == b'{"nodes": [1, 2]}'
    assert _tarball_downloads(env) == 1

    second = _run(env, "--now")
    assert second.returncode == 0, second.stderr
    assert "already up to date" in second.stdout
    assert _tarball_downloads(env) == 1  # no second download


def test_hostile_tar_members_are_ignored(env) -> None:
    store = env["store"]
    assert _run(env, "--now").returncode == 0
    # `../escape.txt` relative to the temp dir would land in the store itself.
    assert not (store / "escape.txt").exists()
    assert not (store.parent / "escape.txt").exists()
    assert not (store / ".graphify_labels.json").exists()  # symlink member skipped
    assert (store / "GRAPH_REPORT.md").read_text() == "# report\n"  # hardlink member skipped
    assert not list(store.glob(".code-graph-tmp-*"))


def test_forced_rebuild_of_the_same_commit_is_downloaded(env) -> None:
    assert _run(env, "--now").returncode == 0
    _publish(env["stub"], built_at="2026-11-26T16:17:00Z", graph=b'{"nodes": [1, 2, 3]}')
    result = _run(env, "--now")
    assert "code graph installed" in result.stdout
    assert (env["store"] / "graph.json").read_bytes() == b'{"nodes": [1, 2, 3]}'
    assert _tarball_downloads(env) == 2


def test_stale_temp_dirs_are_swept(env) -> None:
    leftover = env["store"] / ".code-graph-tmp-killed"
    leftover.mkdir(parents=True)
    (leftover / "graph.json").write_text("half")
    assert _run(env, "--now").returncode == 0
    assert not leftover.exists()


def test_regular_graph_in_worktree_is_left_alone_and_named_in_now_mode(env) -> None:
    out = env["wt"] / "graphify-out"
    out.mkdir()
    (out / "graph.json").write_text("local graph")

    result = _run(env, "--now")
    assert result.returncode == 0, result.stderr
    assert not (out / "graph.json").is_symlink()
    assert (out / "graph.json").read_text() == "local graph"
    assert (out / "GRAPH_REPORT.md").is_symlink()
    assert "keeps its own graph.json" in result.stdout and "just graph-sync" in result.stdout

    (env["bin"] / "gh").unlink()  # hook mode stays silent about it (one line: the gh hint)
    hook = _run(env, stdin=json.dumps({"cwd": str(env["wt"])}))
    assert "keeps its own" not in hook.stdout


def test_hook_mode_returns_at_once_then_throttles(env) -> None:
    env["env"]["STUB_GH_SLEEP"] = "2"
    payload = json.dumps({"hook_event_name": "SessionStart", "cwd": str(env["wt"])})

    marker = env["store"] / ".code-graph-installed.json"
    result = _run(env, stdin=payload)
    assert result.returncode == 0 and result.stdout == ""
    # The hook returned before the (slowed) sync finished: it runs detached. No clock.
    assert not marker.exists()
    assert (env["wt"] / "graphify-out" / "graph.json").is_symlink()

    deadline = time.monotonic() + 30
    while not marker.exists() and time.monotonic() < deadline:
        time.sleep(0.2)
    assert marker.exists(), "background sync did not finish"
    calls = len(_calls(env))

    again = _run(env, stdin=payload)
    assert again.returncode == 0 and again.stdout == ""
    time.sleep(1)
    assert len(_calls(env)) == calls  # throttled: no GitHub call within 30 minutes


@posix_only
def test_lock_prevents_a_second_concurrent_sync(env) -> None:
    import fcntl

    store = env["store"]
    store.mkdir(parents=True)
    with open(store / ".code-graph.lock", "w") as held:
        fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
        result = _run(env, "--now")
    assert result.returncode == 0
    assert "another session is syncing" in result.stdout
    assert _calls(env) == []


def test_missing_gh_exits_zero_with_one_hint_and_still_links(env) -> None:
    (env["bin"] / "gh").unlink()
    payload = json.dumps({"hook_event_name": "SessionStart", "cwd": str(env["wt"])})

    result = _run(env, stdin=payload)
    assert result.returncode == 0
    lines = result.stdout.strip().splitlines()
    assert len(lines) == 1 and "`gh` is missing" in lines[0]
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


# --- Cross-platform unit tests (m-25129418): run on any OS, no subprocess, no network. ---


@pytest.fixture
def mod():
    spec = importlib.util.spec_from_file_location("code_graph_sync", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("platform", ["win32", "linux"])
def test_lock_uses_msvcrt_on_windows_and_flock_elsewhere(mod, monkeypatch, tmp_path, platform):
    held: set[str] = set()

    def grab(key: str) -> None:
        if key in held:
            raise OSError("busy")
        held.add(key)

    fake_msvcrt = types.SimpleNamespace(LK_NBLCK=2, locking=lambda fd, mode, n: grab("msvcrt"))
    fake_fcntl = types.SimpleNamespace(LOCK_EX=2, LOCK_NB=4, flock=lambda fh, op: grab("fcntl"))
    monkeypatch.setitem(sys.modules, "msvcrt", fake_msvcrt)
    monkeypatch.setitem(sys.modules, "fcntl", fake_fcntl)
    monkeypatch.setattr(mod.sys, "platform", platform)
    with open(tmp_path / "lock", "w") as fh:
        assert mod._try_lock(fh) is True
        assert mod._try_lock(fh) is False  # busy -> skip quietly
    assert held == {"msvcrt" if platform == "win32" else "fcntl"}


def test_real_lock_is_exclusive_on_this_os(mod, tmp_path):
    with open(tmp_path / "lock", "w") as first, open(tmp_path / "lock", "w") as second:
        assert mod._try_lock(first) is True
        assert mod._try_lock(second) is False


@pytest.mark.parametrize(
    ("platform", "breakaway_allowed"), [("win32", True), ("win32", False), ("darwin", True)]
)
def test_spawn_detaches_per_platform_and_retries_without_breakaway(
    mod, monkeypatch, platform, breakaway_allowed
):
    monkeypatch.setattr(mod.sys, "platform", platform)
    calls: list[dict] = []

    def popen(cmd, **kwargs):
        calls.append(kwargs)
        if kwargs.get("creationflags", 0) & 0x01000000 and not breakaway_allowed:
            raise PermissionError(13, "Access is denied")
        return "proc"

    assert mod._spawn(["x"], popen=popen) == "proc"
    assert all(c["stdin"] == c["stdout"] == c["stderr"] == subprocess.DEVNULL for c in calls)
    if platform != "win32":
        assert [c["start_new_session"] for c in calls] == [True]
    elif breakaway_allowed:
        assert [c["creationflags"] for c in calls] == [0x01000208]
    else:
        assert [c["creationflags"] for c in calls] == [0x01000208, 0x00000208]


@pytest.mark.parametrize("hardlinks", [True, False])
@pytest.mark.parametrize("rewrite", ["in_place", "new_file"])
def test_link_fallback_keeps_a_placed_file_the_worktree_rewrote(
    mod, monkeypatch, tmp_path, hardlinks, rewrite
):
    _no_symlinks(monkeypatch, mod)
    if not hardlinks:
        monkeypatch.setattr(mod.os, "link", lambda *a, **k: (_ for _ in ()).throw(OSError()))
    store, wt = tmp_path / "store", tmp_path / "wt"
    store.mkdir()
    out = wt / "graphify-out"
    (store / "graph.json").write_text("build 1")
    assert mod.link(str(wt), str(store))[0] == ["graph.json"]

    # A local `graphify update .`: writes through the file, or replaces it with a new one.
    if rewrite == "in_place":
        (out / "graph.json").write_text("local graph, rebuilt here")
    else:
        os.unlink(out / "graph.json")
        (out / "graph.json").write_text("local graph, rebuilt here")
    new = store / "graph.json.new"
    new.write_text("build 2")
    os.replace(new, store / "graph.json")

    for _ in range(2):  # dropped from the marker once, then kept as the worktree's own
        changed, kept = mod.link(str(wt), str(store))
        assert changed == [] and kept == ["graph.json"]
        assert (out / "graph.json").read_text() == "local graph, rebuilt here"
    assert "graph.json" not in json.loads((out / ".code-graph-placed.json").read_text())


def _no_symlinks(monkeypatch, mod) -> None:
    def refuse(*args, **kwargs):
        raise OSError(1314, "A required privilege is not held by the client")

    monkeypatch.setattr(mod.os, "symlink", refuse)


@pytest.mark.parametrize("hardlinks", [True, False])
def test_link_falls_back_to_hardlink_or_copy_and_follows_new_builds(
    mod, monkeypatch, tmp_path, hardlinks
):
    _no_symlinks(monkeypatch, mod)
    if not hardlinks:
        monkeypatch.setattr(mod.os, "link", lambda *a, **k: (_ for _ in ()).throw(OSError()))
    store, wt = tmp_path / "store", tmp_path / "wt"
    store.mkdir()
    wt.mkdir()
    out = wt / "graphify-out"

    # Store still empty (first session): nothing to place, no error.
    assert mod.link(str(wt), str(store)) == ([], [])

    (store / "graph.json").write_text("build 1")
    changed, kept = mod.link(str(wt), str(store))
    assert changed == ["graph.json"] and kept == []
    assert (out / "graph.json").read_text() == "build 1"
    assert not (out / "graph.json").is_symlink()
    assert os.path.samefile(out / "graph.json", store / "graph.json") is hardlinks
    assert mod.link(str(wt), str(store)) == ([], [])  # current: untouched

    new = store / "graph.json.new"  # the installer swaps files in with os.replace
    new.write_text("build 2, longer")
    os.replace(new, store / "graph.json")
    assert mod.link(str(wt), str(store))[0] == ["graph.json"]
    assert (out / "graph.json").read_text() == "build 2, longer"


def test_link_fallback_never_replaces_a_worktrees_own_graph(mod, monkeypatch, tmp_path):
    _no_symlinks(monkeypatch, mod)
    store, out = tmp_path / "store", tmp_path / "wt" / "graphify-out"
    store.mkdir()
    out.mkdir(parents=True)
    (store / "graph.json").write_text("ci build")
    (store / "GRAPH_REPORT.md").write_text("ci report")
    (out / "graph.json").write_text("local graph")

    changed, kept = mod.link(str(tmp_path / "wt"), str(store))
    assert kept == ["graph.json"] and changed == ["GRAPH_REPORT.md"]
    assert (out / "graph.json").read_text() == "local graph"


def test_windows_path_gets_the_github_cli_dir(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    spec = importlib.util.spec_from_file_location("code_graph_sync_win", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert r"C:\Program Files\GitHub CLI" in module._EXTRA_PATH


def _hook_command() -> str:
    settings = json.loads((SCRIPT.parents[1] / ".claude" / "settings.json").read_text())
    return settings["hooks"]["SessionStart"][0]["hooks"][0]["command"]


@pytest.mark.parametrize("store_alias", [True, False])
def test_hook_uses_python_when_python3_is_the_windows_store_alias(tmp_path, store_alias):
    bash = shutil.which("bash")
    if not bash or "system32" in bash.lower():  # WSL's bash cannot see this temp dir
        pytest.skip("no POSIX bash")
    project, bin_dir = tmp_path / "proj", tmp_path / "bin"
    (project / "dev").mkdir(parents=True)
    (project / "dev" / "code-graph-sync.py").write_text("")
    bin_dir.mkdir()
    # The Store alias: found by `command -v`, exits 49 without running anything.
    py3 = "exit 49" if store_alias else '[ "$1" = -c ] || echo "python3 $*"'
    for name, body in (("python3", py3), ("python", '[ "$1" = -c ] || echo "python $*"')):
        stub = bin_dir / name
        stub.write_text(f"#!/bin/sh\n{body}\n")
        stub.chmod(0o755)
    result = subprocess.run(
        [bash, "-c", _hook_command()],
        env={
            **os.environ,
            "PATH": f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}",
            "CLAUDE_PROJECT_DIR": str(project),
        },
        input="{}",
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0
    expected = "python " if store_alias else "python3 "
    assert result.stdout.startswith(expected) and "code-graph-sync.py" in result.stdout
