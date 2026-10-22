import os
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from cryptography.exceptions import InvalidTag

from we2day_api.local_archive import CHUNK, create_key, process


@pytest.fixture
def archive_workspace(tmp_path):
    with TemporaryDirectory(prefix="we2day-archive-", dir=tmp_path) as directory:
        root = Path(directory).resolve()
        assert root.parent == tmp_path.resolve()
        yield root


@pytest.fixture
def archive_files(archive_workspace):
    tmp_path = archive_workspace
    keys = tmp_path / "keys"
    copies = tmp_path / "copies"
    keys.mkdir()
    copies.mkdir()
    key = keys / "key.bin"
    create_key(key)
    return tmp_path / "original.bin", key, copies / "copy.enc"


@pytest.mark.parametrize("size", [0, CHUNK * 2 + 73])
def test_verify_original_without_plaintext_output(archive_files, size):
    source, key, archive = archive_files
    content = os.urandom(size)
    source.write_bytes(content)
    process(source, key, archive)
    saved_archive = archive.read_bytes()
    before = set(archive.parent.iterdir())
    process(archive, key, None, decrypt=True, original=source)
    assert source.read_bytes() == content
    assert archive.read_bytes() == saved_archive
    assert set(archive.parent.iterdir()) == before


@pytest.mark.parametrize("other", [b"different", b"short", b"longer reference"])
def test_verify_original_rejects_different_content_or_length(archive_files, other):
    source, key, archive = archive_files
    source.write_bytes(b"reference")
    process(source, key, archive)
    source.write_bytes(other)
    with pytest.raises(ValueError, match="original_mismatch"):
        process(archive, key, None, decrypt=True, original=source)
    assert source.read_bytes() == other
    assert list(archive.parent.iterdir()) == [archive]


def test_source_and_key_hardlink_alias_rejected(archive_files):
    source, key, archive = archive_files
    os.link(key, source)
    original_key = key.read_bytes()
    with pytest.raises(ValueError, match="separate_key_required"):
        process(source, key, archive)
    assert key.read_bytes() == source.read_bytes() == original_key
    assert not archive.exists()


def test_original_and_key_hardlink_alias_rejected(archive_files):
    source, key, archive = archive_files
    source.write_bytes(b"synthetic reference")
    process(source, key, archive)
    alias = source.parent / "key-alias.bin"
    os.link(key, alias)
    with pytest.raises(ValueError, match="separate_key_required"):
        process(archive, key, None, decrypt=True, original=alias)


def test_verify_original_authentication_failure_leaves_no_output(archive_files):
    source, key, archive = archive_files
    source.write_bytes(b"synthetic reference")
    process(source, key, archive)
    data = bytearray(archive.read_bytes())
    data[-1] ^= 1
    archive.write_bytes(data)
    with pytest.raises(InvalidTag):
        process(archive, key, None, decrypt=True, original=source)
    assert source.read_bytes() == b"synthetic reference"
    assert list(archive.parent.iterdir()) == [archive]


def test_verify_original_cli_success_and_failure_without_disclosure(archive_files):
    from we2day_api import local_archive

    source, key, archive = archive_files
    source.write_bytes(b"synthetic private reference")
    process(source, key, archive)
    command = [
        sys.executable,
        "-m",
        "we2day_api.local_archive",
        "verify",
        "--key",
        str(key),
        "--input",
        str(archive),
        "--original",
        str(source),
    ]
    env = {**os.environ, "PYTHONPATH": str(Path(local_archive.__file__).parents[1])}
    result = subprocess.run(command, env=env, capture_output=True, text=True, check=False)
    assert result.returncode == 0 and result.stdout.startswith("PASS: verify")
    source.write_bytes(b"a different private reference")
    result = subprocess.run(command, env=env, capture_output=True, text=True, check=False)
    assert result.returncode == 1 and result.stdout.startswith("FAIL:")
    assert not result.stderr
    assert str(source) not in result.stdout
    assert "private reference" not in result.stdout
    assert list(archive.parent.iterdir()) == [archive]


@pytest.mark.parametrize("during_verify", [False, True])
def test_same_size_input_change_is_rejected(archive_files, monkeypatch, during_verify):
    source, key, archive = archive_files
    source.write_bytes(b"synthetic reference")
    if during_verify:
        process(source, key, archive)
    real_open = Path.open
    original_stat = source.stat()

    @contextmanager
    def changing_open(path, *args, **kwargs):
        with real_open(path, *args, **kwargs) as file:
            if path != source:
                yield file
                return

            class ChangingReader:
                changed = False

                def fileno(self):
                    return file.fileno()

                def read(self, count=-1):
                    chunk = file.read(count)
                    if chunk and not self.changed:
                        self.changed = True
                        with real_open(source, "r+b") as writer:
                            writer.seek(-1, os.SEEK_END)
                            writer.write(b"!")
                        os.utime(
                            source,
                            ns=(
                                original_stat.st_atime_ns,
                                original_stat.st_mtime_ns + 2_000_000_000,
                            ),
                        )
                    return chunk

            yield ChangingReader()

    monkeypatch.setattr(Path, "open", changing_open)
    with pytest.raises(ValueError, match="original_changed" if during_verify else "source_changed"):
        if during_verify:
            process(archive, key, None, decrypt=True, original=source)
        else:
            process(source, key, archive)
    assert archive.exists() == during_verify
    assert not list(archive.parent.glob(".we2day-partial-*"))


@pytest.mark.parametrize("action", ["keygen", "encrypt", "decrypt"])
def test_original_option_is_verify_only(archive_files, monkeypatch, capsys, action):
    from we2day_api.local_archive import main

    source, key, archive = archive_files
    source.write_bytes(b"synthetic reference")
    target = archive.parent / "must-not-create.bin"
    if action == "decrypt":
        process(source, key, archive)
    command = ["archive", action, "--key", str(target if action == "keygen" else key)]
    if action != "keygen":
        command.extend(
            ["--input", str(archive if action == "decrypt" else source), "--output", str(target)]
        )
    command.extend(["--original", str(source)])
    monkeypatch.setattr("sys.argv", command)
    assert main() == 1 and not target.exists()
    out = capsys.readouterr().out
    assert out.startswith("FAIL:") and str(source) not in out and str(key) not in out


def test_streaming_archive_roundtrip_damage_and_existing_files(archive_workspace):
    tmp_path = archive_workspace
    keys = tmp_path / "keys"
    copies = tmp_path / "copies"
    keys.mkdir()
    copies.mkdir()
    key = keys / "key.bin"
    create_key(key)
    original_key = key.read_bytes()
    with pytest.raises(FileExistsError):
        create_key(key)
    assert key.read_bytes() == original_key
    source = tmp_path / "synthetic.bin"
    content = os.urandom(CHUNK * 2 + 73)
    source.write_bytes(content)
    archive = copies / "copy.enc"
    process(source, key, archive)
    assert archive.read_bytes() != content
    process(archive, key, None, decrypt=True)
    restored = copies / "restored.bin"
    process(archive, key, restored, decrypt=True)
    assert restored.read_bytes() == content and source.read_bytes() == content
    with pytest.raises(ValueError, match="new_output"):
        process(source, key, archive)
    damaged = copies / "damaged.enc"
    data = bytearray(archive.read_bytes())
    data[100] ^= 1
    damaged.write_bytes(data)
    output = copies / "must-not-remain.bin"
    with pytest.raises(InvalidTag):
        process(damaged, key, output, decrypt=True)
    assert not output.exists() and not list(copies.glob(".we2day-partial-*"))
    wrong = keys / "wrong.bin"
    create_key(wrong)
    with pytest.raises(InvalidTag):
        process(archive, wrong, output, decrypt=True)
    assert not output.exists()
    with pytest.raises(ValueError, match="separate_key_directory"):
        process(source, key, keys / "copy.enc")


def test_archive_cli_no_paths_or_contents(archive_workspace, capsys, monkeypatch):
    from we2day_api.local_archive import main

    tmp_path = archive_workspace
    key = tmp_path / "private-key-file"
    monkeypatch.setattr("sys.argv", ["archive", "keygen", "--key", str(key)])
    assert main() == 0
    assert "PASS: keygen" in capsys.readouterr().out
    assert main() == 1
    out = capsys.readouterr().out
    assert str(key) not in out and "private-key-file" not in out
    assert len(key.read_bytes()) == 32
