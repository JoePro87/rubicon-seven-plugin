"""Detached runner for the correction-capture learning loop.

Spawned fire-and-forget from turn_reset.py (UserPromptSubmit) so the player's turn is
never blocked by the Haiku extraction call. Reads a temp JSON payload
{prior_dm, correction, session_id, turn, cache_path, bans_path}, runs capture_correction,
then deletes the temp file. ALL failures exit 0 (fail-open); errors are logged, never raised.
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

ERROR_LOG = Path(__file__).parent / "correction_capture_errors.log"


def _log_error(message: str) -> None:
    try:
        ts = time.strftime("%Y-%m-%dT%H:%M:%S")
        with ERROR_LOG.open("a", encoding="utf-8") as f:
            f.write(f"{ts}  {message}\n")
    except Exception:
        pass


def run(input_file_path: str) -> int:
    input_path = Path(input_file_path)
    try:
        payload = json.loads(input_path.read_text(encoding="utf-8"))
    except Exception as e:
        _log_error(f"failed to read payload {input_file_path}: {e}")
        try:
            input_path.unlink()
        except Exception:
            pass
        return 0
    try:
        try:
            from hooks.correction_capture import capture_correction
            from hooks.distillation_cache import DistillationCache
            from hooks.fabrication_bans import FabricationBans
        except ImportError:
            from correction_capture import capture_correction
            from distillation_cache import DistillationCache
            from fabrication_bans import FabricationBans
        cache = DistillationCache(payload["cache_path"])
        bans = FabricationBans(payload["bans_path"])
        capture_correction(
            prior_dm=payload.get("prior_dm", ""),
            correction=payload.get("correction", ""),
            cache=cache, bans=bans,
            session_id=payload.get("session_id", "unknown"),
            turn=payload.get("turn", 0),
        )
    except Exception as e:
        _log_error(f"capture failed: {e}")
    finally:
        try:
            input_path.unlink()
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(0)
    sys.exit(run(sys.argv[1]))
