import hashlib
import io
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from audit_v04_remote_assets import verify


class RemoteV04AuditTests(unittest.TestCase):
    def test_download_hash_range_and_failure_gate(self):
        row = {"logical_path": "reference.fna", "url": "https://huggingface.co/datasets/liurulong/terminator/resolve/" + "a" * 40 + "/v0.4.0/reference.fna", "byte_size": "4", "sha256": hashlib.sha256(b"ACGT").hexdigest(), "asset_kind": "fasta"}
        def response(data, status, headers=None):
            result = io.BytesIO(data)
            result.status = status
            result.headers = headers or {}
            return result
        with patch("audit_v04_remote_assets.urlopen", side_effect=[response(b"ACGT", 200), response(b"A", 206, {"Content-Range": "bytes 0-0/4", "Access-Control-Allow-Origin": "*"})]):
            self.assertEqual(verify(row)["status"], "verified")
        with patch("audit_v04_remote_assets.urlopen", return_value=response(b"AAAA", 200)):
            self.assertEqual(verify(row)["error"], "SHA-256 mismatch")
        with patch("audit_v04_remote_assets.urlopen") as request:
            self.assertEqual(verify({**row, "url": "https://example.org/file"})["status"], "failed")
            request.assert_not_called()


if __name__ == "__main__":
    unittest.main()
