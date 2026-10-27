"""Run from an unpacked source tree, without installation or executable bits."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))
from evidence_ledger.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
