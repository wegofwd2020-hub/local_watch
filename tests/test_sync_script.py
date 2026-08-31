"""Guards for deploy/sync-to-aggregator.sh.

The aggregator was configured with LOCAL_WATCH_REMOTE still pointing at
itself, so it rsynced to its own Tailscale IP and failed every cycle with
"Too many authentication failures" — an ssh error that gives the operator no
hint that the real problem is a machine trying to sync to itself.
"""
import os
import pathlib
import shutil
import subprocess

REPO = pathlib.Path(__file__).parent.parent
SCRIPT = REPO / "deploy" / "sync-to-aggregator.sh"
THIS_HOST = os.uname().nodename.split(".")[0]


def run(tmp_path, remote, snapshot=True, path_prefix=None):
    data = tmp_path / "data"
    (data / "spool").mkdir(parents=True)
    if snapshot:
        (data / "spool" / f"{THIS_HOST}.json").write_text("{}")
    env = {
        "PATH": f"{path_prefix}:{os.environ['PATH']}" if path_prefix else os.environ["PATH"],
        "HOME": str(tmp_path),          # no ~/.config/local_watch/env to source
        "LOCAL_WATCH_DATA": str(data),
        "LOCAL_WATCH_REMOTE": remote,
    }
    return subprocess.run([str(SCRIPT)], env=env, capture_output=True, text=True)


def fake_rsync(tmp_path):
    """A stub rsync on PATH that records the arguments it was handed."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    log = tmp_path / "rsync.args"
    (bindir / "rsync").write_text(f'#!/bin/sh\nprintf "%s\\n" "$@" > {log}\n')
    (bindir / "rsync").chmod(0o755)
    return str(bindir), log


def test_refuses_to_sync_to_itself(tmp_path):
    result = run(tmp_path, f"sivam@{THIS_HOST}.tail242406.ts.net")
    assert result.returncode != 0


def test_self_sync_message_explains_the_actual_problem(tmp_path):
    # "Too many authentication failures" sent the operator looking at ssh keys.
    out = run(tmp_path, f"sivam@{THIS_HOST}.tail242406.ts.net").stderr.lower()
    assert "itself" in out or "aggregator" in out
    assert "local_watch_remote" in out


def test_bare_hostname_self_target_is_also_caught(tmp_path):
    assert run(tmp_path, f"sivam@{THIS_HOST}").returncode != 0


def test_empty_remote_fails_with_a_usable_message(tmp_path):
    result = run(tmp_path, "")
    assert result.returncode != 0
    assert "local_watch_remote" in result.stderr.lower()


def test_missing_snapshot_exits_zero(tmp_path):
    # Nothing to push yet is not an error: the aggregator's staleness rule is
    # what reports the gap, and failing here would just add noise.
    result = run(tmp_path, "sivam@somewhere-else.example.net", snapshot=False)
    assert result.returncode == 0


def test_a_genuinely_remote_host_is_not_mistaken_for_self(tmp_path):
    bindir, log = fake_rsync(tmp_path)
    result = run(tmp_path, "sivam@other-box.tail242406.ts.net", path_prefix=bindir)
    assert result.returncode == 0, result.stderr
    assert log.exists(), "rsync was never invoked"


def test_pushes_the_snapshot_to_the_aggregator_ingest_dir(tmp_path):
    bindir, log = fake_rsync(tmp_path)
    run(tmp_path, "sivam@other-box.tail242406.ts.net", path_prefix=bindir)
    args = log.read_text().splitlines()
    assert args[-1] == "sivam@other-box.tail242406.ts.net:.local/share/local_watch/ingest/"
    assert args[-2].endswith(f"/spool/{THIS_HOST}.json")


def test_script_is_executable():
    assert shutil.which(str(SCRIPT)) or os.access(SCRIPT, os.X_OK)
