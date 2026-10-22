"""Offline single-file encryption. Never connects to DB/Storage or restores a live system."""

import argparse
import hashlib
import hmac
import os
from pathlib import Path
from tempfile import NamedTemporaryFile

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

MAGIC = b"WE2DAY-ARCHIVE-1\x00"
CHUNK = 1024 * 1024
MAX_BYTES = 16 * 1024**3


def regular(path: Path) -> Path:
    if path.is_symlink() or not path.is_file():
        raise ValueError("regular_file_required")
    return path.resolve(strict=True)


def key_bytes(path: Path) -> bytes:
    with regular(path).open("rb") as file:
        value = file.read(33)
    if len(value) != 32:
        raise ValueError("invalid_key")
    return value


def create_key(path: Path):
    # On Windows, secure parent-directory ACLs must be configured by the operator.
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as file:
        file.write(os.urandom(32))
        file.flush()
        os.fsync(file.fileno())


def fingerprint(file) -> tuple[int, int, int]:
    info = os.fstat(file.fileno())
    return info.st_size, info.st_mtime_ns, info.st_ctime_ns


def compare_original(path: Path, expected_digest: bytes, expected_size: int):
    digest = hashlib.sha256()
    with path.open("rb") as file:
        before = fingerprint(file)
        if before[0] != expected_size:
            raise ValueError("original_mismatch")
        remaining = expected_size
        while remaining:
            chunk = file.read(min(CHUNK, remaining))
            if not chunk:
                raise ValueError("original_changed")
            remaining -= len(chunk)
            digest.update(chunk)
        if file.read(1) or fingerprint(file) != before:
            raise ValueError("original_changed")
    if not hmac.compare_digest(digest.digest(), expected_digest):
        raise ValueError("original_mismatch")


def process(
    source: Path,
    key_path: Path,
    destination: Path | None,
    decrypt=False,
    *,
    original: Path | None = None,
):
    if original is not None and (not decrypt or destination is not None):
        raise ValueError("original_verify_only")
    source = regular(source)
    key_path = regular(key_path)
    if source.samefile(key_path):
        raise ValueError("separate_key_required")
    if original is not None:
        original = regular(original)
        if original.samefile(key_path):
            raise ValueError("separate_key_required")
    key = key_bytes(key_path)
    if source.stat().st_size > MAX_BYTES + 128:
        raise ValueError("file_too_large")
    if destination:
        if not destination.parent.is_dir() or destination.exists() or destination.is_symlink():
            raise ValueError("new_output_required")
        destination = destination.parent.resolve(strict=True) / destination.name
        if destination in {source, key_path}:
            raise ValueError("new_output_required")
        if not decrypt and destination.parent == key_path.parent:
            raise ValueError("separate_key_directory_required")
    temporary = None
    try:
        output = None
        if destination:
            output = NamedTemporaryFile(
                prefix=".we2day-partial-", dir=destination.parent, delete=False
            )
            temporary = Path(output.name)
        try:
            with source.open("rb") as file:
                before = fingerprint(file)
                size = before[0]
                if decrypt:
                    header = file.read(len(MAGIC) + 12)
                    if len(header) != len(MAGIC) + 12 or not header.startswith(MAGIC):
                        raise ValueError("invalid_archive")
                    remaining = size - len(header) - 16
                    if remaining < 0 or remaining > MAX_BYTES:
                        raise ValueError("invalid_archive")
                    file.seek(-16, os.SEEK_END)
                    tag = file.read(16)
                    file.seek(len(header))
                    context = Cipher(algorithms.AES(key), modes.GCM(header[-12:], tag)).decryptor()
                else:
                    remaining = size
                    if remaining > MAX_BYTES:
                        raise ValueError("file_too_large")
                    header = MAGIC + os.urandom(12)
                    context = Cipher(algorithms.AES(key), modes.GCM(header[-12:])).encryptor()
                    if output:
                        output.write(header)
                plaintext_size = remaining
                digest = hashlib.sha256() if original is not None else None
                context.authenticate_additional_data(header)
                while remaining:
                    chunk = file.read(min(CHUNK, remaining))
                    if not chunk:
                        raise ValueError("source_changed")
                    remaining -= len(chunk)
                    converted = context.update(chunk)
                    if digest is not None:
                        digest.update(converted)
                    if output:
                        output.write(converted)
                tail = context.finalize()
                if digest is not None:
                    digest.update(tail)
                if output:
                    output.write(tail)
                    if not decrypt:
                        output.write(context.tag)
                    output.flush()
                    os.fsync(output.fileno())
                if fingerprint(file) != before:
                    raise ValueError("source_changed")
            if original is not None and digest is not None:
                compare_original(original, digest.digest(), plaintext_size)
        finally:
            if output:
                output.close()
        if destination and temporary:
            # Same-directory hard link atomically refuses an existing destination.
            # Never replace a file or reuse a previous partial result.
            os.link(temporary, destination)
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(
        description="Offline encrypted file; no DB export or live restore"
    )
    parser.add_argument("action", choices=["keygen", "encrypt", "verify", "decrypt"])
    parser.add_argument("--key", type=Path, required=True)
    parser.add_argument("--input", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--original", type=Path, help="Compare with a closed original file (verify only)"
    )
    args = parser.parse_args()
    try:
        if args.action == "keygen":
            if args.input or args.output or args.original:
                raise ValueError("invalid_arguments")
            create_key(args.key)
        else:
            if not args.input or (args.action == "verify") == bool(args.output):
                raise ValueError("invalid_arguments")
            if args.original is not None and args.action != "verify":
                raise ValueError("invalid_arguments")
            process(
                args.input,
                args.key,
                args.output,
                decrypt=args.action != "encrypt",
                original=args.original,
            )
        detail = "; original content matched" if args.action == "verify" and args.original else ""
        print("PASS: " + args.action + detail + "; no live system changes")
        return 0
    except (OSError, ValueError, InvalidTag):
        print("FAIL: file, key, authentication or new output requirement")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
