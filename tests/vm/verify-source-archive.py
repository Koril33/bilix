"""Reject VM state and private keys from a Linux GUI source archive."""

import argparse
import tarfile
from pathlib import PurePosixPath

FORBIDDEN_PARTS = {".git", ".vagrant", ".venv", "__pycache__", "build", "dist"}
FORBIDDEN_SUFFIXES = {".key", ".pem", ".p12", ".pfx", ".rsa"}
# Keep the marker split so this audit script does not flag its own source.
PRIVATE_KEY_MARKERS = (
    b"-----BEGIN " + b"OPENSSH PRIVATE KEY-----",
    b"-----BEGIN " + b"RSA PRIVATE KEY-----",
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive")
    args = parser.parse_args()
    seen = set()
    with tarfile.open(args.archive, "r:gz") as archive:
        for member in archive:
            path = PurePosixPath(member.name)
            if (
                path.is_absolute()
                or ".." in path.parts
                or any(part.lower() in FORBIDDEN_PARTS for part in path.parts)
                or path.suffix.lower() in FORBIDDEN_SUFFIXES
            ):
                raise RuntimeError(f"Unsafe source archive path: {member.name}")
            if not member.isfile() and not member.isdir():
                raise RuntimeError(f"Unexpected source archive entry: {member.name}")
            if not member.isfile():
                continue
            seen.add(path.name)
            stream = archive.extractfile(member)
            if stream is None:
                raise RuntimeError(f"Cannot read archived source: {member.name}")
            content = stream.read()
            if any(marker in content for marker in PRIVATE_KEY_MARKERS):
                raise RuntimeError(f"Private key content found in source archive: {member.name}")
    if not {"pyproject.toml", "uv.lock", "LICENSE"}.issubset(seen):
        raise RuntimeError("The source archive is missing required release files")
    print(f"Source archive passed path and private-key checks: {args.archive}")


if __name__ == "__main__":
    main()
