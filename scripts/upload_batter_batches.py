#!/usr/bin/env python3
"""Upload validated BATTER genome batches strictly after remote processing completes.

Each numbered object directory (000/, 001/, ...) is uploaded through a private
remote staging location, atomically published into the watched directory, and
finally given an empty READY marker.  The next batch is not uploaded until the
remote worker writes a completion JSON record that matches this upload's
manifest digest and unique upload ID.

This adapts the tested GTDB promoter uploader's staged SFTP and durable receipt
protocol to BATTER's mixed FASTA, GFF3, index, and metadata files. The remote
terminator worker must be adapted before this is run without --dry-run.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple

BATCH_RE = re.compile(r"^[0-9]{3}$")
STATE_VERSION = 1


class UploadError(RuntimeError):
    """Raised when a batch cannot safely advance."""


class RemoteTransportError(UploadError):
    """Raised when SSH/SFTP cannot reach the remote host."""


def positive_integer(value: str) -> int:
    try:
        number = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("not an integer: %s" % value) from error
    if number < 1:
        raise argparse.ArgumentTypeError("must be positive: %s" % value)
    return number


def nonnegative_integer(value: str) -> int:
    try:
        number = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("not an integer: %s" % value) from error
    if number < 0:
        raise argparse.ArgumentTypeError("must be non-negative: %s" % value)
    return number


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Upload numbered BATTER genome batches sequentially via SFTP."
    )
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--remote", required=True, help="OpenSSH destination, e.g. root@host")
    parser.add_argument("--remote-root", required=True, help="remote terminator batch directory")
    parser.add_argument("--remote-log-dir", required=True, help="remote completion JSON directory")
    parser.add_argument("--remote-staging-root", required=True)
    parser.add_argument("--state-dir", type=Path, required=True)
    parser.add_argument("--identity", type=Path, help="private key passed to ssh and sftp")
    parser.add_argument("--port", type=positive_integer, help="SSH port")
    parser.add_argument("--start-batch", help="first three-digit batch to process")
    parser.add_argument("--end-batch", help="last three-digit batch to process")
    parser.add_argument("--poll-seconds", type=positive_integer, default=60)
    parser.add_argument(
        "--remote-retry-seconds",
        type=positive_integer,
        default=60,
        help="wait before retrying a temporarily unreachable remote host (default: 60)",
    )
    parser.add_argument(
        "--sftp-chunk-size",
        type=positive_integer,
        default=25,
        help="files sent in each short SFTP connection (default: 25)",
    )
    parser.add_argument(
        "--sftp-retries",
        type=nonnegative_integer,
        default=5,
        help="additional retries after an SFTP connection failure (default: 5)",
    )
    parser.add_argument(
        "--sftp-retry-seconds",
        type=positive_integer,
        default=10,
        help="seconds to wait before an SFTP reconnect (default: 10)",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=nonnegative_integer,
        default=0,
        help="maximum wait per batch; 0 waits indefinitely (default: 0)",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--receiver-confirmed", action="store_true",
        help="explicit confirmation that the separate terminator worker and receipt path are ready",
    )
    parser.add_argument(
        "--force-unlock",
        action="store_true",
        help="remove a stale local uploader lock before starting",
    )
    parser.add_argument(
        "--recover-partial-published",
        action="store_true",
        help=(
            "explicitly reconcile a manifest-verified partial final tree from its "
            "exact private stage after removing its stale READY marker"
        ),
    )
    return parser.parse_args()


def utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def atomic_write_json(path: Path, value: Dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name("." + path.name + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(path)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def discover_batches(source_root: Path, start: Optional[str], end: Optional[str]) -> List[Path]:
    if not source_root.is_dir():
        raise NotADirectoryError("source root not found: %s" % source_root)
    for value, option in ((start, "--start-batch"), (end, "--end-batch")):
        if value is not None and not BATCH_RE.fullmatch(value):
            raise ValueError("%s must be a three-digit batch ID" % option)
    if start and end and int(start) > int(end):
        raise ValueError("--start-batch must not exceed --end-batch")

    batches = sorted(
        (path for path in source_root.iterdir() if path.is_dir() and BATCH_RE.fullmatch(path.name)),
        key=lambda path: int(path.name),
    )
    selected = [
        path for path in batches
        if (start is None or path.name >= start) and (end is None or path.name <= end)
    ]
    if not selected:
        raise ValueError("no numbered batch directories selected below %s" % source_root)
    expected = range(int(selected[0].name), int(selected[-1].name) + 1)
    actual = [int(path.name) for path in selected]
    if actual != list(expected):
        raise ValueError("selected batch directories are not contiguous")
    return selected


def build_manifest(batch_dir: Path) -> Tuple[List[Dict[str, object]], str]:
    files: List[Tuple[str, Path]] = []
    for path in sorted(batch_dir.rglob("*")):
        if path.is_symlink():
            raise ValueError("BATTER batch may not contain symlinks: %s" % path)
        if not path.is_file():
            continue
        rel = path.relative_to(batch_dir).as_posix()
        pieces = rel.split("/")
        if len(pieces) == 1 and rel in {"genomes.tsv", "files.tsv"}:
            pass
        elif (len(pieces) == 3 and pieces[0] == "genomes"
              and re.fullmatch(r"[A-Za-z0-9_.-]+", pieces[1])
              and pieces[2] in {
                  "reference.fa.gz", "reference.fa.gz.fai", "reference.fa.gz.gzi",
                  "prediction.gff3.gz", "prediction.gff3.gz.tbi",
                  "augmentation.gff3.gz", "augmentation.gff3.gz.tbi",
                  "genes.gff3.gz", "genes.gff3.gz.tbi", "metadata.json",
              }):
            pass
        else:
            raise ValueError("unexpected BATTER batch file: %s" % rel)
        if ".." in rel.split("/") or rel.startswith("/"):
            raise ValueError("unsafe release file path: %s" % rel)
        files.append((rel, path))
    if not (batch_dir / "genomes.tsv").is_file() or not (batch_dir / "files.tsv").is_file():
        raise ValueError("BATTER batch lacks genomes.tsv or files.tsv: %s" % batch_dir)
    genome_dirs = list((batch_dir / "genomes").iterdir()) if (batch_dir / "genomes").is_dir() else []
    if not 1 <= len(genome_dirs) <= 1000:
        raise ValueError("BATTER batch must contain 1-1000 genome directories")
    for folder in genome_dirs:
        if not folder.is_dir():
            raise ValueError("unexpected entry below genomes/: %s" % folder)
        names = {entry.name for entry in folder.iterdir() if entry.is_file()}
        required = {"reference.fa.gz", "reference.fa.gz.fai", "reference.fa.gz.gzi",
                    "prediction.gff3.gz", "prediction.gff3.gz.tbi",
                    "augmentation.gff3.gz", "metadata.json"}
        if not required <= names or (("genes.gff3.gz" in names) != ("genes.gff3.gz.tbi" in names)):
            raise ValueError("incomplete BATTER genome package: %s" % folder)
    rows: List[Dict[str, object]] = []
    for rel, path in files:
        if any(character in rel for character in "\t\r\n"):
            raise ValueError("unsafe release file path: %s" % rel)
        rows.append({"name": rel, "bytes": path.stat().st_size, "sha256": sha256_file(path)})
    expected_inventory = {
        str(row["name"]): (int(row["bytes"]), str(row["sha256"]))
        for row in rows if row["name"] != "files.tsv"
    }
    recorded_inventory: Dict[str, Tuple[int, str]] = {}
    with (batch_dir / "files.tsv").open(encoding="utf-8", newline="") as handle:
        for fields in csv.reader(handle, delimiter="\t"):
            if len(fields) != 3:
                raise ValueError("invalid BATTER files.tsv row: %s" % batch_dir)
            name, size, digest = fields
            if name in recorded_inventory or not re.fullmatch(r"[0-9a-f]{64}", digest):
                raise ValueError("duplicate or invalid BATTER files.tsv entry: %s" % name)
            try:
                recorded_inventory[name] = (int(size), digest)
            except ValueError as error:
                raise ValueError("invalid BATTER files.tsv size: %s" % name) from error
    if recorded_inventory != expected_inventory:
        raise ValueError("BATTER files.tsv checksum or inventory differs: %s" % batch_dir)
    payload = "".join(
        "%s\t%d\t%s\n" % (row["name"], row["bytes"], row["sha256"])
        for row in rows
    ).encode("utf-8")
    return rows, hashlib.sha256(payload).hexdigest()


def write_manifest(directory: Path, rows: Iterable[Dict[str, object]]) -> Path:
    path = directory / "manifest.tsv"
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        for row in rows:
            writer.writerow((row["name"], row["bytes"], row["sha256"]))
    return path


def shell_quote(value: str) -> str:
    return shlex.quote(value)


class Remote:
    def __init__(self, remote: str, identity: Optional[Path], port: Optional[int]) -> None:
        self.remote = remote
        self.identity = identity
        self.port = port

    def ssh_command(self, command: str) -> List[str]:
        result = ["ssh"]
        if self.identity:
            result.extend(("-i", str(self.identity)))
        if self.port:
            result.extend(("-p", str(self.port)))
        return result + [self.remote, command]

    def sftp_command(self) -> List[str]:
        result = [
            "sftp", "-b", "-", "-o", "BatchMode=yes",
            "-o", "ConnectTimeout=20", "-o", "IdentitiesOnly=yes",
        ]
        if self.identity:
            result.extend(("-i", str(self.identity)))
        if self.port:
            result.extend(("-P", str(self.port)))
        return result + [self.remote]

    def run_ssh(self, command: str) -> str:
        completed = subprocess.run(
            self.ssh_command(command), text=True, capture_output=True, check=False
        )
        if completed.returncode:
            message = "remote command failed (%d): %s\n%s" % (
                completed.returncode, completed.stderr.strip(), command
            )
            if completed.returncode == 255:
                raise RemoteTransportError(message)
            raise UploadError(message)
        return completed.stdout

    @staticmethod
    def _is_transport_failure(returncode: int, stderr: str) -> bool:
        text = stderr.lower()
        # OpenSSH SFTP also returns 255 for ordinary batch-command failures.
        # On this endpoint a missing ``-ls`` target is followed by the normal
        # session-close text "closed by remote host", so the missing target
        # remains an inventory result rather than a reconnect condition.
        if "not found" in text:
            return False
        return returncode < 0 or any(phrase in text for phrase in (
            "connection reset", "closed by remote host",
            "connection timed out", "could not resolve hostname", "broken pipe",
            "no route to host", "connection refused", "authentication failed",
            "ssh_exchange_identification",
        ))

    def run_sftp_capture(self, commands: Sequence[str]) -> str:
        completed = subprocess.run(
            self.sftp_command(), input="\n".join(commands) + "\n", text=True,
            capture_output=True, check=False,
        )
        if completed.returncode:
            message = "SFTP operation failed (%d): %s" % (
                completed.returncode, completed.stderr.strip()
            )
            if self._is_transport_failure(completed.returncode, completed.stderr):
                raise RemoteTransportError(message)
            raise UploadError(message)
        return completed.stdout

    def run_sftp(self, commands: Sequence[str]) -> None:
        self.run_sftp_capture(commands)

    def read_file(self, path: str) -> Optional[str]:
        """Read a remote text file through SFTP; return None when absent."""
        with tempfile.TemporaryDirectory(prefix="terminator-remote-") as directory:
            temporary = Path(directory) / "download"
            try:
                self.run_sftp_capture(["get %s %s" % (shell_quote(path), shell_quote(str(temporary)))])
            except RemoteTransportError:
                raise
            except UploadError:
                if temporary.exists():
                    raise
                return None
            return temporary.read_text(encoding="utf-8")

    def read_files(self, paths: Sequence[str]) -> Dict[str, Optional[str]]:
        """Download remote text files in bounded SFTP sessions."""
        with tempfile.TemporaryDirectory(prefix="terminator-remote-files-") as directory:
            local_paths = {path: Path(directory) / ("file-%06d" % index)
                           for index, path in enumerate(paths)}
            for start in range(0, len(paths), 25):
                group = paths[start : start + 25]
                commands = [
                    "get %s %s" % (shell_quote(path), shell_quote(str(local_paths[path])))
                    for path in group
                ]
                completed = subprocess.run(
                    self.sftp_command(), input="\n".join(commands) + "\n", text=True,
                    capture_output=True, check=False,
                )
                if self._is_transport_failure(completed.returncode, completed.stderr):
                    raise RemoteTransportError(
                        "SFTP operation failed (%d): %s" % (completed.returncode, completed.stderr.strip())
                    )
            return {
                path: local_path.read_text(encoding="utf-8") if local_path.exists() else None
                for path, local_path in local_paths.items()
            }

    def file_sizes(self, paths: Sequence[str]) -> Dict[str, int]:
        """Return remote file sizes through bounded resumable SFTP listings."""
        sizes = {}
        for start in range(0, len(paths), 100):
            commands = ["-ls -l %s" % shell_quote(path) for path in paths[start : start + 100]]
            for attempt in range(5):
                completed = subprocess.run(
                    self.sftp_command(), input="\n".join(commands) + "\n", text=True,
                    capture_output=True, check=False,
                )
                if not self._is_transport_failure(completed.returncode, completed.stderr):
                    break
                if attempt == 4:
                    raise RemoteTransportError(
                        "SFTP operation failed (%d): %s" % (
                            completed.returncode, completed.stderr.strip()
                        )
                    )
                # Retry only the interrupted inventory slice. Retrying the
                # whole 3,000-file scan after one transient tunnel reset turns
                # a brief outage into a continuous connection burst.
                time.sleep(5)
            # This SFTP endpoint returns 255 for an optional ``-ls`` command
            # whose target is absent. That simply means the expected payload
            # was not found; parse all successful listings from stdout.
            output = completed.stdout
            for line in output.splitlines():
                if not line.startswith("-"):
                    continue
                fields = line.split(maxsplit=8)
                if len(fields) != 9:
                    continue
                try:
                    size = int(fields[4])
                except ValueError:
                    continue
                sizes[fields[8]] = size
        return sizes

    def path_exists(self, path: str) -> bool:
        """Probe a remote path using the SFTP client's ls operation."""
        try:
            self.run_sftp_capture(["ls %s" % shell_quote(path)])
        except RemoteTransportError:
            raise
        except UploadError:
            return False
        return True

    def directory_entries(self, path: str) -> set[str]:
        """Return immediate entry names from a remote SFTP directory."""
        output = self.run_sftp_capture(["ls %s" % shell_quote(path)])
        prefix = path.rstrip("/") + "/"
        entries = set()
        for line in output.splitlines():
            value = line.strip()
            if not value:
                continue
            if value.startswith(prefix):
                value = value[len(prefix):]
            if "/" not in value:
                entries.add(value)
        return entries

    def mkdir_many(self, paths: Sequence[str]) -> None:
        """Create directories in one SFTP session, ignoring existing entries."""
        directories = set()
        for path in paths:
            normalized = path.rstrip("/") or "/"
            current = ""
            for part in normalized.split("/"):
                if not part:
                    current = "/"
                    continue
                current = (current.rstrip("/") + "/" + part) if current != "/" else "/" + part
                directories.add(current)
        commands = ["-mkdir %s" % shell_quote(path) for path in sorted(directories, key=lambda value: (value.count("/"), value))]
        if commands:
            self.run_sftp(commands)

    def mkdir_p(self, path: str) -> None:
        """Create a remote directory tree using OpenSSH 7.4-compatible SFTP."""
        self.mkdir_many([path])

    def rename(self, source: str, destination: str) -> None:
        self.run_sftp(["rename %s %s" % (shell_quote(source), shell_quote(destination))])

    def publish_tree(
        self, stage_dir: str, final_dir: str, rows: Sequence[Dict[str, object]],
    ) -> None:
        """Publish a large object tree when directory rename is unsupported."""
        file_names = [str(row["name"]) for row in rows]
        expected = set(file_names)
        matched_final, mismatched_final = remote_manifest_inventory(self, final_dir, rows)
        if mismatched_final:
            raise UploadError("refusing to overwrite mismatched final payloads")
        matched_stage, mismatched_stage = remote_manifest_inventory(self, stage_dir, rows)
        if mismatched_stage:
            raise UploadError("private stage contains mismatched payloads")
        missing = expected - matched_final
        unavailable = missing - matched_stage
        if unavailable:
            raise UploadError(
                "private stage lacks %d payloads required for publication" % len(unavailable)
            )
        to_move = sorted(missing)
        object_names = sorted({name.split("/", 1)[0] for name in to_move if "/" in name})
        # The SFTP server returns a batch failure when asked to mkdir an
        # existing directory, even with OpenSSH's error-ignoring command
        # prefix. On a resumed file-level publish, list the final root and
        # create only directories which do not already exist.
        final_exists = self.path_exists(final_dir)
        existing_objects = self.directory_entries(final_dir) if final_exists else set()
        directory_commands = []
        if not final_exists:
            directory_commands.append("-mkdir %s" % shell_quote(final_dir))
        directory_commands.extend(
            "-mkdir %s" % shell_quote(final_dir + "/" + name)
            for name in object_names if name not in existing_objects
        )
        existing_genomes = (
            self.directory_entries(final_dir + "/genomes")
            if "genomes" in existing_objects else set()
        )
        genome_names = sorted({name.split("/")[1] for name in to_move if name.startswith("genomes/")})
        directory_commands.extend(
            "-mkdir %s" % shell_quote(final_dir + "/genomes/" + name)
            for name in genome_names if name not in existing_genomes
        )
        if directory_commands:
            self.run_sftp(directory_commands)
        # Move only payloads still absent from final. This preserves an
        # interrupted file-level publish without treating missing old sources
        # as a transport failure or overwriting a validated destination.
        for start in range(0, len(to_move), 100):
            self.run_sftp([
                "rename %s %s" % (
                    shell_quote(stage_dir + "/" + name),
                    shell_quote(final_dir + "/" + name),
                )
                for name in to_move[start : start + 100]
            ])
        matched, mismatched = remote_manifest_inventory(self, final_dir, rows)
        if mismatched or matched != expected:
            raise UploadError(
                "file-level publish is incomplete; missing=%d mismatched=%d"
                % (len(expected - matched), len(mismatched))
            )
        for name in ("manifest.tsv", "upload_metadata.json"):
            destination = final_dir + "/" + name
            if self.path_exists(destination):
                continue
            source = stage_dir + "/" + name
            if not self.path_exists(source):
                raise UploadError("private stage lacks required control file: %s" % name)
            self.rename(source, destination)

    def remove(self, path: str) -> None:
        self.run_sftp(["-rm %s" % shell_quote(path)])
        if self.path_exists(path):
            raise UploadError("could not remove remote path: %s" % path)

    def put_empty(self, destination: str) -> None:
        with tempfile.NamedTemporaryFile(prefix="batter-ready-", delete=False) as handle:
            temporary = Path(handle.name)
        try:
            self.run_sftp(["put %s %s" % (shell_quote(str(temporary)), shell_quote(destination))])
        finally:
            temporary.unlink(missing_ok=True)


def completion_path(log_dir: str, batch: str, upload_id: str, kind: str) -> str:
    return "%s/terminator.%s.%s.%s.json" % (log_dir.rstrip("/"), batch, upload_id, kind)


def read_remote_json(remote: Remote, path: str) -> Optional[Dict[str, object]]:
    if hasattr(remote, "read_file"):
        output = remote.read_file(path)
    else:  # Retain compatibility with the lightweight test doubles.
        output = remote.run_ssh("if test -f %s; then cat %s; fi" % (shell_quote(path), shell_quote(path)))
    if not output or not output.strip():
        return None
    try:
        value = json.loads(output)
    except json.JSONDecodeError as error:
        raise UploadError("remote completion marker is not valid JSON: %s" % path) from error
    if not isinstance(value, dict):
        raise UploadError("remote completion marker is not a JSON object: %s" % path)
    return value


def validate_marker(marker: Dict[str, object], batch: str, upload_id: str, manifest_sha256: str, status: str) -> None:
    expected = {
        "batch": batch,
        "upload_id": upload_id,
        "manifest_sha256": manifest_sha256,
        "status": status,
    }
    mismatches = [key for key, value in expected.items() if marker.get(key) != value]
    if mismatches or not isinstance(marker.get("completed_at"), str):
        raise UploadError("remote %s marker has mismatched or missing provenance" % status)


def state_path(state_dir: Path, batch: str) -> Path:
    return state_dir / (batch + ".json")


def load_state(path: Path) -> Optional[Dict[str, object]]:
    if not path.exists():
        return None
    try:
        with path.open(encoding="utf-8") as handle:
            state = json.load(handle)
    except (OSError, json.JSONDecodeError) as error:
        raise UploadError("unreadable state file: %s" % path) from error
    if not isinstance(state, dict) or state.get("version") != STATE_VERSION:
        raise UploadError("unsupported state file: %s" % path)
    return state


def save_state(path: Path, state: Dict[str, object], stage: str, **updates: object) -> None:
    state.update(updates)
    state["stage"] = stage
    state["updated_at"] = utc_now()
    atomic_write_json(path, state)


def new_state(
    batch: str, source_root: Path, remote_root: str, remote_log_dir: str,
    remote_staging_root: str, rows: List[Dict[str, object]], digest: str,
) -> Dict[str, object]:
    upload_id = uuid.uuid4().hex
    stage_dir = "%s/%s.%s" % (remote_staging_root.rstrip("/"), batch, upload_id)
    return {
        "version": STATE_VERSION,
        "batch": batch,
        "source_root": str(source_root),
        "remote_root": remote_root,
        "remote_log_dir": remote_log_dir,
        "remote_staging_root": remote_staging_root,
        "upload_id": upload_id,
        "manifest": rows,
        "manifest_sha256": digest,
        "remote_stage_dir": stage_dir,
        "remote_final_dir": "%s/%s" % (remote_root.rstrip("/"), batch),
        "stage": "discovered",
        "created_at": utc_now(),
        "updated_at": utc_now(),
    }


def validate_state(state: Dict[str, object], source_root: Path, remote_root: str, digest: str) -> None:
    expected = {
        "source_root": str(source_root),
        "remote_root": remote_root,
        "manifest_sha256": digest,
    }
    mismatches = [key for key, value in expected.items() if state.get(key) != value]
    if mismatches:
        raise UploadError("state does not match current batch configuration: %s" % ", ".join(mismatches))
    if not isinstance(state.get("remote_log_dir"), str) or not str(state["remote_log_dir"]).strip():
        raise UploadError("state lacks a valid remote_log_dir")


def remote_path_exists(remote: Remote, path: str) -> bool:
    if hasattr(remote, "path_exists"):
        return remote.path_exists(path)
    return remote.run_ssh(
        "if test -e %s; then printf present; fi" % shell_quote(path)
    ).strip() == "present"


def remote_read_text(remote: Remote, path: str) -> Optional[str]:
    if hasattr(remote, "read_file"):
        return remote.read_file(path)
    output = remote.run_ssh(
        "if test -f %s; then cat %s; fi" % (shell_quote(path), shell_quote(path))
    )
    return output or None


def expected_manifest_text(state: Dict[str, object]) -> str:
    return "".join(
        "%s\t%d\t%s\n" % (row["name"], int(row["bytes"]), row["sha256"])
        for row in state["manifest"]
    )


def remote_metadata_matches_state(remote: Remote, state: Dict[str, object]) -> bool:
    output = remote_read_text(remote, str(state["remote_final_dir"]) + "/upload_metadata.json")
    if not output:
        return False
    try:
        metadata = json.loads(output)
    except json.JSONDecodeError:
        return False
    return (
        isinstance(metadata, dict)
        and all(
            metadata.get(key) == state[key]
            for key in ("batch", "upload_id", "manifest_sha256", "remote_log_dir")
        )
    )


def remote_final_matches_state(remote: Remote, state: Dict[str, object]) -> bool:
    """Return whether final data and controls exactly match this upload state."""
    final_dir = str(state["remote_final_dir"])
    if not remote_metadata_matches_state(remote, state):
        return False
    if remote_read_text(remote, final_dir + "/manifest.tsv") != expected_manifest_text(state):
        return False
    matched, mismatched = remote_manifest_inventory(remote, final_dir, state["manifest"])
    expected = {str(row["name"]) for row in state["manifest"]}
    return not mismatched and matched == expected


def ensure_final_directory_is_safe(remote: Remote, state: Dict[str, object]) -> bool:
    """Return whether this exact upload has completely published remotely."""
    final_dir = str(state["remote_final_dir"])
    if not remote_path_exists(remote, final_dir):
        return False
    if remote_final_matches_state(remote, state):
        return True

    metadata = remote_read_text(remote, final_dir + "/upload_metadata.json")
    manifest = remote_read_text(remote, final_dir + "/manifest.tsv")
    if metadata and not remote_metadata_matches_state(remote, state):
        raise UploadError("remote final metadata conflicts with this upload: %s" % final_dir)
    if manifest and manifest != expected_manifest_text(state):
        raise UploadError("remote final manifest conflicts with this upload: %s" % final_dir)
    _, mismatched = remote_manifest_inventory(remote, final_dir, state["manifest"])
    if mismatched:
        raise UploadError("remote final contains mismatched payloads: %s" % final_dir)
    if hasattr(remote, "publish_tree") and remote_directory_exists(remote, str(state["remote_stage_dir"])):
        # A file-level SFTP publish may have moved some payloads before a
        # connection interruption. Only the exact private stage may repair it.
        return False
    raise UploadError(
        "remote final directory is incomplete and no exact private stage remains: %s"
        % final_dir
    )


def remote_directory_exists(remote: Remote, path: str) -> bool:
    if hasattr(remote, "path_exists"):
        return remote.path_exists(path)
    return remote.run_ssh(
        "if test -d %s; then printf present; fi" % shell_quote(path)
    ).strip() == "present"


def waiting_remote_needs_recovery(remote: Remote, state: Dict[str, object]) -> bool:
    """Return whether a marker-less waiting batch can resume its exact stage."""
    # The worker can remove upload_metadata.json before it atomically publishes
    # the terminal marker.  In waiting_remote, any remaining final-path entry is
    # therefore ambiguous and must not authorize a replay or overwrite.
    if remote_path_exists(remote, str(state["remote_final_dir"])):
        return False
    return remote_directory_exists(remote, str(state["remote_stage_dir"]))


def partial_final_is_recoverable(remote: Remote, state: Dict[str, object]) -> bool:
    """Return whether an explicit retry may repair this exact partial publish."""
    final_dir = str(state["remote_final_dir"])
    if not remote_path_exists(remote, final_dir) or remote_final_matches_state(remote, state):
        return False
    if not remote_metadata_matches_state(remote, state):
        return False
    manifest = remote_read_text(remote, final_dir + "/manifest.tsv")
    if manifest != expected_manifest_text(state):
        return False
    matched_final, mismatched = remote_manifest_inventory(remote, final_dir, state["manifest"])
    if mismatched or not remote_directory_exists(remote, str(state["remote_stage_dir"])):
        return False
    missing = {str(row["name"]) for row in state["manifest"]} - matched_final
    matched_stage, stage_mismatched = remote_manifest_inventory(
        remote, str(state["remote_stage_dir"]), state["manifest"]
    )
    return bool(missing) and not stage_mismatched and missing <= matched_stage


def remove_stale_ready(remote: Remote, state: Dict[str, object]) -> None:
    """Remove a previously emitted READY only during explicit exact-stage recovery."""
    ready_path = str(state["remote_final_dir"]) + "/READY"
    if not remote_path_exists(remote, ready_path):
        return
    if hasattr(remote, "remove"):
        remote.remove(ready_path)
    else:
        remote.run_ssh("rm -f %s" % shell_quote(ready_path))
    if remote_path_exists(remote, ready_path):
        raise UploadError("stale READY remains visible for partial batch %s" % state["batch"])


def prepare_stage(remote: Remote, state: Dict[str, object]) -> None:
    """Create this upload's staging directory and its object subdirectories."""
    stage_dir = str(state["remote_stage_dir"])
    subdirs = sorted({
        "/".join(str(row["name"]).split("/")[:-1])
        for row in state["manifest"] if "/" in str(row["name"])
    })
    if hasattr(remote, "mkdir_many"):
        remote.mkdir_many(
            [str(state["remote_staging_root"]), stage_dir]
            + [stage_dir + "/" + subdir for subdir in subdirs]
        )
        remote.run_sftp(["chmod 700 %s" % shell_quote(stage_dir)])
        return
    if hasattr(remote, "mkdir_p"):
        remote.mkdir_p(str(state["remote_staging_root"]))
        remote.mkdir_p(stage_dir)
        for subdir in subdirs:
            remote.mkdir_p(stage_dir + "/" + subdir)
        if hasattr(remote, "run_sftp"):
            remote.run_sftp(["chmod 700 %s" % shell_quote(stage_dir)])
        return
    commands = [
        "mkdir -p %s" % shell_quote(str(state["remote_staging_root"])),
        "mkdir -p %s" % shell_quote(stage_dir),
    ]
    commands.extend("mkdir -p %s" % shell_quote(stage_dir + "/" + subdir) for subdir in subdirs)
    remote.run_ssh(" && ".join(commands + ["chmod 700 %s" % shell_quote(stage_dir)]))


def remote_manifest_inventory(
    remote: Remote, directory: str, rows: Iterable[Dict[str, object]],
) -> Tuple[set[str], set[str]]:
    """Return manifest names with matching and mismatched remote payload sizes.

    SFTP has no remote checksum command, so resumable transfer and file-level
    publication use exact sizes. The worker still performs authoritative
    SHA-256 validation from ``manifest.tsv`` before emitting completion.
    """
    expected = list(rows)
    if hasattr(remote, "file_sizes"):
        paths = {str(row["name"]): directory + "/" + str(row["name"]) for row in expected}
        expected_sizes = {str(row["name"]): int(row["bytes"]) for row in expected}
        sizes = remote.file_sizes(list(paths.values()))
        matched = {
            name for name, path in paths.items()
            if sizes.get(path) == expected_sizes[name]
        }
        mismatched = {
            name for name, path in paths.items()
            if path in sizes and sizes[path] != expected_sizes[name]
        }
        return matched, mismatched
    checks = []
    for row in expected:
        name = str(row["name"])
        path = directory + "/" + name
        checks.append(
            "if test -f {path} && test \"$(wc -c < {path})\" -eq {bytes} && "
            "test \"$(sha256sum {path} | cut -d ' ' -f1)\" = {sha}; then printf '%s\\n' {name}; fi".format(
                path=shell_quote(path),
                bytes=int(row["bytes"]),
                sha=shell_quote(str(row["sha256"])),
                name=shell_quote(name),
            )
        )
    output = remote.run_ssh("set -eu\n" + "\n".join(checks))
    names = set(filter(None, output.splitlines()))
    expected_names = {str(row["name"]) for row in expected}
    if not names <= expected_names:
        raise UploadError("remote manifest scan returned an unexpected filename")
    return names, set()


def scan_matching_stage_files(
    remote: Remote, state: Dict[str, object], rows: Iterable[Dict[str, object]],
) -> set[str]:
    matched, mismatched = remote_manifest_inventory(remote, str(state["remote_stage_dir"]), rows)
    if mismatched:
        raise UploadError("remote staging contains mismatched payloads")
    return matched


def quarantine_partial_stage_files(
    remote: Remote, state: Dict[str, object], rows: Iterable[Dict[str, object]],
    mismatched: set[str],
) -> None:
    """Preserve interrupted private-stage payloads before retransmitting them."""
    stage_dir = str(state["remote_stage_dir"])
    names = {str(row["name"]) for row in rows}
    if not mismatched <= names:
        raise UploadError("remote staging scan returned an unexpected filename")
    for name in sorted(mismatched):
        source = stage_dir + "/" + name
        destination = source + ".partial-" + uuid.uuid4().hex
        # A dropped SFTP upload can leave a truncated source in private staging.
        # Preserve it for audit instead of deleting or overwriting it; the next
        # pass uploads the immutable local payload to the original path.
        remote.rename(source, destination)
        print("Quarantined partial staged payload: %s" % name, flush=True)


def chunks(items: List[Dict[str, object]], size: int) -> Iterable[List[Dict[str, object]]]:
    for start in range(0, len(items), size):
        yield items[start : start + size]


def sftp_put_rows(remote: Remote, stage_dir: str, batch_dir: Path, rows: List[Dict[str, object]]) -> None:
    commands = []
    for row in rows:
        source = batch_dir / str(row["name"])
        commands.append(
            "put %s %s" % (
                shell_quote(str(source)), shell_quote(stage_dir + "/" + str(row["name"]))
            )
        )
    remote.run_sftp(commands)


def upload_stage(
    remote: Remote, state: Dict[str, object], batch_dir: Path, work_dir: Path,
    chunk_size: int, retries: int, retry_seconds: int,
) -> None:
    stage_dir = str(state["remote_stage_dir"])
    expected = list(state["manifest"])
    attempts = 0
    finished = 0
    for group in chunks(expected, chunk_size):
        while True:
            matched, mismatched = remote_manifest_inventory(remote, stage_dir, group)
            if mismatched:
                quarantine_partial_stage_files(remote, state, group, mismatched)
                continue
            pending = [row for row in group if str(row["name"]) not in matched]
            if not pending:
                break
            try:
                sftp_put_rows(remote, stage_dir, batch_dir, pending)
            except RemoteTransportError as error:
                attempts += 1
                if attempts > retries:
                    raise RemoteTransportError(
                        "SFTP retries exhausted with %d files still pending: %s"
                        % (len(pending), error)
                    ) from error
                print(
                    "SFTP connection failed; retrying after %d seconds (%d/%d)"
                    % (retry_seconds, attempts, retries),
                    flush=True,
                )
                time.sleep(retry_seconds)
                continue
            break
        finished += len(group)
        print(
            "Batch %s staging transfer attempts: %d/%d files"
            % (state["batch"], finished, len(expected)),
            flush=True,
        )

    manifest = write_manifest(work_dir, expected)
    metadata = work_dir / "upload_metadata.json"
    metadata.write_text(
        json.dumps({
            "batch": state["batch"], "upload_id": state["upload_id"],
            "manifest_sha256": state["manifest_sha256"], "created_at": state["created_at"],
            "remote_log_dir": state["remote_log_dir"],
        }, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    controls = [
        "put %s %s" % (shell_quote(str(manifest)), shell_quote(stage_dir + "/manifest.tsv")),
        "put %s %s" % (shell_quote(str(metadata)), shell_quote(stage_dir + "/upload_metadata.json")),
    ]
    for attempt in range(retries + 1):
        try:
            remote.run_sftp(controls)
            return
        except RemoteTransportError as error:
            if attempt == retries:
                raise RemoteTransportError(
                    "SFTP retries exhausted uploading control files: %s" % error
                ) from error
            time.sleep(retry_seconds)


def verify_stage(remote: Remote, state: Dict[str, object]) -> None:
    stage_dir = str(state["remote_stage_dir"])
    manifest_path = stage_dir + "/manifest.tsv"
    metadata_path = stage_dir + "/upload_metadata.json"
    if hasattr(remote, "read_file"):
        manifest = remote.read_file(manifest_path)
        metadata = remote.read_file(metadata_path)
        if manifest is None or metadata is None:
            raise UploadError("remote staging is missing manifest or upload metadata")
        if manifest != expected_manifest_text(state):
            raise UploadError("remote staging manifest does not match local state")
        try:
            value = json.loads(metadata)
        except json.JSONDecodeError as error:
            raise UploadError("remote staging metadata is not valid JSON") from error
        if not isinstance(value, dict) or any(
            value.get(key) != state[key]
            for key in ("batch", "upload_id", "manifest_sha256", "remote_log_dir")
        ):
            raise UploadError("remote staging metadata does not match local state")
    else:
        command = """set -eu
while IFS='\\t' read -r name bytes sha256; do
    test -n \"$name\"
    test \"$(wc -c < %s/\"$name\")\" -eq \"$bytes\"
    test \"$(sha256sum %s/\"$name\" | cut -d ' ' -f1)\" = \"$sha256\"
done < %s
test -f %s/upload_metadata.json
""" % (
            shell_quote(stage_dir), shell_quote(stage_dir), shell_quote(manifest_path),
            shell_quote(stage_dir),
        )
        remote.run_ssh(command)

    matched, mismatched = remote_manifest_inventory(remote, stage_dir, state["manifest"])
    expected = {str(row["name"]) for row in state["manifest"]}
    missing = expected - matched
    if missing or mismatched:
        raise UploadError(
            "remote staging payload inventory is incomplete; missing=%d mismatched=%d"
            % (len(missing), len(mismatched))
        )


def publish_batch(remote: Remote, state: Dict[str, object]) -> None:
    stage_dir = str(state["remote_stage_dir"])
    final_dir = str(state["remote_final_dir"])
    if hasattr(remote, "publish_tree"):
        remote.publish_tree(stage_dir, final_dir, list(state["manifest"]))
        return
    if hasattr(remote, "rename"):
        remote.rename(stage_dir, final_dir)
        return
    remote.run_ssh(
        "if test -e %s; then exit 18; fi; test -d %s; mv %s %s"
        % (shell_quote(final_dir), shell_quote(stage_dir), shell_quote(stage_dir), shell_quote(final_dir))
    )


def send_ready(remote: Remote, state: Dict[str, object]) -> None:
    if not remote_final_matches_state(remote, state):
        raise UploadError("refusing to send READY for an incomplete final batch")
    final_dir = str(state["remote_final_dir"])
    ready_path = final_dir + "/READY"
    if hasattr(remote, "put_empty"):
        remote.put_empty(ready_path)
        return
    remote.run_ssh(
        "test -d %s && : > %s && test -f %s"
        % (shell_quote(final_dir), shell_quote(ready_path), shell_quote(ready_path))
    )


def terminal_completion_marker(remote: Remote, state: Dict[str, object]) -> Optional[Dict[str, object]]:
    """Return this upload's completion marker or raise for a failure marker."""
    batch = str(state["batch"])
    upload_id = str(state["upload_id"])
    digest = str(state["manifest_sha256"])
    log_dir = str(state["remote_log_dir"])
    failed = read_remote_json(remote, completion_path(log_dir, batch, upload_id, "failed"))
    if failed is not None:
        validate_marker(failed, batch, upload_id, digest, "failed")
        raise UploadError(
            "remote processing failed for batch %s: %s"
            % (batch, failed.get("error", "no error summary"))
        )
    completed = read_remote_json(remote, completion_path(log_dir, batch, upload_id, "complete"))
    if completed is not None:
        validate_marker(completed, batch, upload_id, digest, "complete")
    return completed


def wait_for_completion(
    remote: Remote, state: Dict[str, object], poll_seconds: int, timeout_seconds: int,
    remote_retry_seconds: int, reconcile: Optional[Callable[[], bool]] = None,
) -> Optional[Dict[str, object]]:
    """Wait for a terminal marker, or return None when exact-stage recovery is needed."""
    batch = str(state["batch"])
    started = time.monotonic()
    while True:
        try:
            completed = terminal_completion_marker(remote, state)
            if completed is not None:
                return completed
            if reconcile is not None and reconcile():
                return None
        except RemoteTransportError as error:
            if timeout_seconds and time.monotonic() - started >= timeout_seconds:
                raise UploadError("timed out waiting for remote completion of batch %s" % batch) from error
            print(
                "Remote host unavailable while waiting for batch %s; retrying in %d seconds: %s"
                % (batch, remote_retry_seconds, str(error).splitlines()[0]),
                flush=True,
            )
            time.sleep(remote_retry_seconds)
            continue
        if timeout_seconds and time.monotonic() - started >= timeout_seconds:
            raise UploadError("timed out waiting for remote completion of batch %s" % batch)
        print("Waiting for remote completion of batch %s ..." % batch, flush=True)
        time.sleep(poll_seconds)


def acquire_lock(state_dir: Path, force_unlock: bool) -> Tuple[int, str]:
    state_dir.mkdir(parents=True, exist_ok=True)
    token = uuid.uuid4().hex
    lock = state_dir / ".upload.lock"
    if force_unlock:
        lock.unlink(missing_ok=True)
    try:
        descriptor = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as error:
        raise UploadError("another uploader may be running (lock: %s)" % lock) from error
    os.write(descriptor, ("token=%s pid=%d started=%s\n" % (token, os.getpid(), utc_now())).encode("ascii"))
    os.fsync(descriptor)
    return descriptor, token


def release_lock(state_dir: Path, descriptor: int, token: str) -> None:
    lock = state_dir / ".upload.lock"
    try:
        try:
            contents = lock.read_text(encoding="ascii")
        except OSError:
            contents = ""
        if ("token=%s\n" % token) in contents or contents.startswith("token=%s " % token):
            lock.unlink(missing_ok=True)
    finally:
        os.close(descriptor)


def ensure_predecessors_completed(args: argparse.Namespace, remote: Remote, first_batch: str) -> None:
    """Prevent a restricted run from bypassing the global numeric sequence."""
    predecessors = []
    for number in range(int(first_batch)):
        batch = "%03d" % number
        state = load_state(state_path(args.state_dir, batch))
        if state is None or state.get("stage") != "complete":
            raise UploadError("cannot start batch %s before confirmed completion of %s" % (first_batch, batch))
        path = completion_path(
            str(state["remote_log_dir"]), batch, str(state.get("upload_id", "")), "complete"
        )
        predecessors.append((batch, state, path))

    if hasattr(remote, "read_files"):
        contents = remote.read_files([path for _batch, _state, path in predecessors])
        for batch, state, path in predecessors:
            output = contents.get(path)
            if not output or not output.strip():
                raise UploadError("predecessor batch %s lacks its remote completion JSON" % batch)
            try:
                marker = json.loads(output)
            except json.JSONDecodeError as error:
                raise UploadError("remote completion marker is not valid JSON: %s" % path) from error
            if not isinstance(marker, dict):
                raise UploadError("remote completion marker is not a JSON object: %s" % path)
            validate_marker(
                marker, batch, str(state.get("upload_id", "")),
                str(state.get("manifest_sha256", "")), "complete",
            )
        return

    for batch, state, path in predecessors:
        marker = read_remote_json(remote, path)
        if marker is None:
            raise UploadError("predecessor batch %s lacks its remote completion JSON" % batch)
        validate_marker(
            marker, batch, str(state.get("upload_id", "")),
            str(state.get("manifest_sha256", "")), "complete",
        )


def process_batch(args: argparse.Namespace, remote: Remote, batch_dir: Path) -> None:
    batch = batch_dir.name
    rows, digest = build_manifest(batch_dir)
    path = state_path(args.state_dir, batch)
    state = load_state(path)
    if state is None:
        state = new_state(batch, args.source_root, args.remote_root, args.remote_log_dir, args.remote_staging_root, rows, digest)
        atomic_write_json(path, state)
    else:
        validate_state(state, args.source_root, args.remote_root, digest)

    stage = str(state["stage"])
    completed = terminal_completion_marker(remote, state)
    if completed is not None:
        if stage != "complete":
            save_state(path, state, "complete", completed_at=completed["completed_at"])
        print("Batch %s is already complete." % batch, flush=True)
        return
    if stage == "complete":
        raise UploadError("completed batch %s lacks its remote completion JSON" % batch)

    while True:
        if stage == "waiting_remote" and getattr(args, "recover_partial_published", False):
            if partial_final_is_recoverable(remote, state):
                remove_stale_ready(remote, state)
                state.pop("ready_at", None)
                save_state(
                    path, state, "uploaded", recovered_at=utc_now(),
                    recovery_reason="explicit partial final-tree recovery from exact private stage",
                )
                stage = "uploaded"
                print(
                    "Recovering partial batch %s from its exact remote staging directory" % batch,
                    flush=True,
                )
                continue
        if stage == "waiting_remote":
            marker = wait_for_completion(
                remote, state, args.poll_seconds, args.timeout_seconds,
                args.remote_retry_seconds,
                reconcile=lambda: waiting_remote_needs_recovery(remote, state),
            )
            if marker is not None:
                save_state(path, state, "complete", completed_at=marker["completed_at"])
                print("Completed batch %s" % batch, flush=True)
                return
            # A successful publish atomically moves this exact directory, so its
            # continued existence proves this upload was not published. Resume
            # its checksummed private stage instead of waiting forever.
            state.pop("ready_at", None)
            save_state(
                path, state, "staging", recovered_at=utc_now(),
                recovery_reason="published directory absent; exact staging directory remains",
            )
            stage = "staging"
            print(
                "Recovering batch %s from its existing remote staging directory" % batch,
                flush=True,
            )
            continue

        published_remotely = ensure_final_directory_is_safe(remote, state)
        if stage == "published" and not published_remotely:
            if getattr(args, "recover_partial_published", False) and partial_final_is_recoverable(remote, state):
                remove_stale_ready(remote, state)
                save_state(
                    path, state, "uploaded", recovered_at=utc_now(),
                    recovery_reason="explicit partial published-state recovery from exact private stage",
                )
                stage = "uploaded"
                continue
            raise UploadError("published batch %s no longer has a complete final tree" % batch)
        if stage == "discovered":
            if published_remotely:
                save_state(path, state, "published")
                stage = "published"
            else:
                prepare_stage(remote, state)
                save_state(path, state, "staging")
                stage = "staging"
        if stage == "staging":
            # The staging directory may have been manually cleaned after an
            # interrupted transfer. Recreate the dedicated, un-published location
            # before retrying the idempotent full batch upload.
            prepare_stage(remote, state)
            print("Uploading BATTER batch %s (%d files)" % (batch, len(rows)), flush=True)
            while True:
                with tempfile.TemporaryDirectory(prefix="terminator-upload-") as temporary:
                    upload_stage(
                        remote, state, batch_dir, Path(temporary), args.sftp_chunk_size,
                        args.sftp_retries, args.sftp_retry_seconds,
                    )
                _, current_digest = build_manifest(batch_dir)
                if current_digest != digest:
                    raise UploadError("source batch changed while it was being uploaded: %s" % batch)
                try:
                    verify_stage(remote, state)
                except RemoteTransportError:
                    raise
                except UploadError as error:
                    reconcilable = (
                        "remote staging payload inventory is incomplete",
                        "remote staging is missing manifest or upload metadata",
                        "remote staging manifest does not match local state",
                        "remote staging metadata is not valid JSON",
                        "remote staging metadata does not match local state",
                    )
                    if not str(error).startswith(reconcilable):
                        raise
                    # A successful SFTP batch can still leave individual
                    # payloads or control files absent after a connection
                    # interruption. Re-run the idempotent chunk inventory so
                    # only missing paths are retransmitted or quarantined.
                    print(
                        "Batch %s stage verification is incomplete; reconciling exact staging: %s"
                        % (batch, error),
                        flush=True,
                    )
                    continue
                break
            print(
                "Batch %s stage verified: %d/%d manifest payloads"
                % (batch, len(rows), len(rows)),
                flush=True,
            )
            save_state(path, state, "uploaded")
            stage = "uploaded"
        if stage == "uploaded":
            if published_remotely:
                save_state(path, state, "published")
            else:
                # A prior uploader could have counted attempted transfers as a
                # complete stage. If no final path exists, repair this exact
                # private transaction before any file-level publication.
                if not remote_path_exists(remote, str(state["remote_final_dir"])):
                    try:
                        verify_stage(remote, state)
                    except RemoteTransportError:
                        raise
                    except UploadError as error:
                        save_state(
                            path, state, "staging", recovered_at=utc_now(),
                            recovery_reason=(
                                "uploaded state failed private-stage verification before "
                                "publication: %s" % error
                            ),
                        )
                        stage = "staging"
                        print(
                            "Recovering batch %s from its exact private staging directory"
                            % batch,
                            flush=True,
                        )
                        continue
                print("Publishing batch %s" % batch, flush=True)
                publish_batch(remote, state)
                if not ensure_final_directory_is_safe(remote, state):
                    raise UploadError("published batch %s is not visible remotely" % batch)
                save_state(path, state, "published")
            stage = "published"
        if stage == "published":
            print("Sending READY for batch %s" % batch, flush=True)
            send_ready(remote, state)
            save_state(path, state, "waiting_remote", ready_at=utc_now())
            stage = "waiting_remote"
        if stage != "waiting_remote":
            raise UploadError("unknown state stage for batch %s: %s" % (batch, stage))


def process_batch_with_remote_retry(
    args: argparse.Namespace, remote: Remote, batch_dir: Path,
) -> None:
    """Resume the durable batch state after temporary remote transport failures."""
    while True:
        try:
            process_batch(args, remote, batch_dir)
            return
        except RemoteTransportError as error:
            print(
                "Remote host unavailable while processing batch %s; retrying in %d seconds: %s"
                % (batch_dir.name, args.remote_retry_seconds, str(error).splitlines()[0]),
                flush=True,
            )
            time.sleep(args.remote_retry_seconds)


def main() -> int:
    args = parse_args()
    args.source_root = args.source_root.resolve()
    args.state_dir = args.state_dir.resolve()
    if args.identity:
        args.identity = args.identity.expanduser()
        if not args.identity.is_file():
            raise FileNotFoundError("SSH identity not found: %s" % args.identity)
    batches = discover_batches(args.source_root, args.start_batch, args.end_batch)
    print("Selected batches: %s through %s (%d total)" % (batches[0].name, batches[-1].name, len(batches)), flush=True)
    if args.dry_run:
        for batch_dir in batches:
            rows, digest = build_manifest(batch_dir)
            print("Would upload BATTER batch %s: %d files, manifest %s" % (batch_dir.name, len(rows), digest), flush=True)
        return 0

    audit_path = args.source_root.parent / "audit.json"
    if not audit_path.is_file() or not json.loads(audit_path.read_text(encoding="utf-8")).get("complete"):
        raise UploadError("BATTER release preparation is incomplete; refusing remote upload")
    if not args.receiver_confirmed:
        raise UploadError("terminator receiver is not confirmed; use --dry-run for local preview")

    descriptor, lock_token = acquire_lock(args.state_dir, args.force_unlock)
    try:
        remote = Remote(args.remote, args.identity, args.port)
        while True:
            try:
                ensure_predecessors_completed(args, remote, batches[0].name)
                break
            except RemoteTransportError as error:
                print(
                    "Remote host unavailable while validating predecessor batches; "
                    "retrying in %d seconds: %s"
                    % (args.remote_retry_seconds, str(error).splitlines()[0]),
                    flush=True,
                )
                time.sleep(args.remote_retry_seconds)
        for batch_dir in batches:
            process_batch_with_remote_retry(args, remote, batch_dir)
    finally:
        release_lock(args.state_dir, descriptor, lock_token)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, UploadError, ValueError) as error:
        print("ERROR: %s" % error, file=sys.stderr)
        raise SystemExit(1)
