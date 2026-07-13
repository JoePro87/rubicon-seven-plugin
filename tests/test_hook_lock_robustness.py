"""Root-cause regression tests for the hook state lock (the full-suite-only flake).

The flake: under full-suite load on Windows, `hooks/hook_utils.file_lock`
intermittently raised `PermissionError [WinError 32]` (a sharing violation the
acquire loop didn't catch) or `TimeoutError: Could not acquire state file lock`
(a lock left by a killed hook subprocess was only declared stale after 10s, but
the acquire timeout was 5s — so a leftover lock guaranteed a timeout). Confirmed
by a 40-thread stress reproduction (35/40 failures pre-fix).

These two tests reproduce both modes deterministically with a per-test temp lock
(never touches the real .hook_state.lock).
"""
import time
import threading
from pathlib import Path
import importlib.util

HOOK = Path(__file__).resolve().parents[1] / "hooks" / "hook_utils.py"
spec = importlib.util.spec_from_file_location("hook_utils", HOOK)
hook_utils = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hook_utils)
file_lock = hook_utils.file_lock


def test_file_lock_survives_concurrent_contention(tmp_path):
    """Many threads racing on the same lock file must all acquire it without a
    single uncaught error — Windows raises WinError 32 (not FileExistsError)
    when two processes hit the lock file at the same instant."""
    lp = tmp_path / "contended.lock"
    errors, acquired = [], []
    guard = threading.Lock()

    def worker(i):
        try:
            with file_lock(lock_path=lp, timeout=15.0):
                with guard:
                    acquired.append(i)
                time.sleep(0.005)
        except Exception as e:  # noqa: BLE001 — we want ANY error to fail the test
            with guard:
                errors.append((type(e).__name__, str(e)))

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"file_lock raised under contention: {errors[:5]}"
    assert len(acquired) == 20


def test_file_lock_recovers_leftover_lock_within_timeout(tmp_path):
    """A lock left behind by a crashed/killed holder must be reclaimed WITHIN the
    acquire timeout — i.e. the stale threshold must be shorter than the timeout,
    or a leftover lock poisons every waiter."""
    lp = tmp_path / "leftover.lock"
    lp.write_text(str(time.time()))  # a fresh leftover lock (age ~0)

    t0 = time.time()
    with file_lock(lock_path=lp, timeout=8.0):
        pass  # must reach here, not raise TimeoutError
    elapsed = time.time() - t0
    assert elapsed < 8.0, f"leftover lock not reclaimed within timeout ({elapsed:.1f}s)"
