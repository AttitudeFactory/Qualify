"""The measurement driver cannot inherit host secrets or escape its isolated network."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.parametrize("status", [0, 1, 137])
def test_memory_driver_isolated_and_preserves_verdict(tmp_path, status):
    binary = tmp_path / "docker"
    log = tmp_path / "calls.jsonl"
    binary.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, sys\n"
        "args=sys.argv[1:]\n"
        "with open(os.environ['MEMORY_TEST_LOG'],'a') as out: out.write(json.dumps(args)+'\\n')\n"
        "if '/measure/creative_worker_memory.py' in args and '--serve-r2' not in args:\n"
        "    sys.exit(int(os.environ['MEMORY_TEST_STATUS']))\n"
    )
    binary.chmod(0o755)
    sleep = tmp_path / "sleep"
    sleep.write_text("#!/bin/sh\nexit 0\n")
    sleep.chmod(0o755)
    result = subprocess.run(
        ["bash", str(ROOT / "deploy/measure/creative-worker-memory.sh")],
        cwd=ROOT,
        env={
            **os.environ,
            "PATH": str(tmp_path) + os.pathsep + os.environ["PATH"],
            "MEMORY_TEST_LOG": str(log),
            "MEMORY_TEST_STATUS": str(status),
            "QUALIFY_ANTHROPIC_API_KEY": "host-secret-must-not-forward",
        },
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == status, result.stderr
    calls = [json.loads(line) for line in log.read_text().splitlines()]
    assert any(call[:3] == ["network", "create", "--internal"] for call in calls)
    worker = next(
        call
        for call in calls
        if "/measure/creative_worker_memory.py" in call and "--serve-r2" not in call
    )
    assert worker[worker.index("--memory") + 1] == "512m"
    assert worker[worker.index("--memory-swap") + 1] == "512m"
    assert "--env-file" not in worker and "--privileged" not in worker
    assert not {"-p", "--publish", "--network=host"}.intersection(worker)
    assert "host-secret-must-not-forward" not in json.dumps(calls)
    assert "QUALIFY_CREATIVE_DISPATCHER=queue" in worker
    assert "QUALIFY_CREATIONS_QUOTA=off" in worker
    assert any(call[:2] == ["network", "rm"] for call in calls)
    assert any(call[:2] == ["rm", "-f"] and any("worker" in arg for arg in call) for call in calls)
    if status == 137:
        assert "OOM-killed" in result.stdout
