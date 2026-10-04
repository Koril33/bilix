"""Write a binary Git file list for the Linux VM's Git-free source snapshot."""

import hashlib
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DESTINATION = ROOT / "dist" / "gui" / "cache" / "source-files.nul"


def main() -> None:
    result = subprocess.run(
        ["git", "-C", str(ROOT), "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        check=True,
        capture_output=True,
    )
    if not result.stdout.endswith(b"\0"):
        raise RuntimeError("Git returned an empty or invalid source file list")
    DESTINATION.parent.mkdir(parents=True, exist_ok=True)
    DESTINATION.write_bytes(result.stdout)
    print(f"{DESTINATION}: {result.stdout.count(bytes([0]))} files")
    print(f"sha256={hashlib.sha256(result.stdout).hexdigest()}")


if __name__ == "__main__":
    main()
