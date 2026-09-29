import json
import subprocess
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
WORKER = REPO_ROOT / "prototype/accession-range/src/worker.js"


class WorkerAssetProxyTests(unittest.TestCase):
    def run_worker(
        self,
        *,
        request_url: str = "http://localhost:8787",
        request_path: str | None = None,
        local_asset_base: str | None = None,
        fetch_mode: str = "success",
        data_release_manifest_mode: str = "valid",
    ) -> dict[str, object]:
        worker_path = json.dumps(str(WORKER))
        request_url_js = json.dumps(request_url)
        request_path_js = json.dumps(request_path)
        local_asset_base_js = json.dumps(local_asset_base)
        fetch_mode_js = json.dumps(fetch_mode)
        data_release_manifest_mode_js = json.dumps(data_release_manifest_mode)
        script = f"""
import {{ readFileSync }} from "node:fs";

const source = readFileSync({worker_path}, "utf8")
  .replace("export default {{", "const worker = {{") + "\\nexport {{ worker }};";
const moduleUrl = "data:text/javascript;base64," + Buffer.from(source).toString("base64");
const {{ worker }} = await import(moduleUrl);

const release = {{
  release_version: "v0.4.0",
  status: "preview",
  canonical_manifest_path: "data/public/v0.4.0/release.json",
  canonical_manifest_sha256: "a".repeat(64),
  asset_origin_status: "verified",
  materializer_version: "test",
  is_current: 1,
}};
const asset = {{
  asset_key: "v0.4.0--assembly-GCF_000009045.1--fai",
  release_version: "v0.4.0",
  assembly_accession: "GCF_000009045.1",
  source_id: null,
  asset_kind: "fai",
  logical_path: "assemblies/GCF_000009045.1/reference/reference.fna.fai",
  origin_host: "huggingface.co",
  content_type: "text/plain",
  byte_size: 29,
  sha256: "b".repeat(64),
  supports_range: 1,
  redistribution_status: "verified_redistributable",
  is_public: 1,
}};
const browserAssembly = {{
  accession: "GCF_000009045.1",
  display_name: "Bacillus subtilis subsp. subtilis str. 168",
  organism_name: "Bacillus subtilis",
}};
const browserTracks = [{{
  track_id: "track-BATTER_S1_003",
  release_version: "v0.4.0",
  source_id: "BATTER_S1_003",
  assembly_accession: "GCF_000009045.1",
  assay: "Term-seq",
  record_count: 1070,
  raw_accessions_json: "[]",
  paper_title: "Test paper",
  pmid: "12345678",
  doi: "10.1000/test",
  metadata_json: JSON.stringify({{citation: {{authors: "A Researcher; B Researcher", journal: "Test Journal", paper_title: "Test paper", published_year: 2026, pubmed_url: "https://pubmed.ncbi.nlm.nih.gov/12345678/"}}, article_license: "CC BY 4.0", known_limitations: "One condition"}}),
  is_public: 1,
  asset_key: "v0.4.0--study-GCF_000009045.1-PMID_12345678",
}}];
const browserSource = {{
  source_id: "BATTER_S1_003",
  release_version: "v0.4.0",
  release_status: "published_standardized",
  evidence_class: "author_called_endpoint",
  record_count: 1070,
  has_jbrowse: 1,
  record_root: "genomes/GCF_000009045.1/studies/PMID_12345678/endpoints.gff3.gz",
}};
const studyGff = {{
  asset_key: "v0.4.0--study-GCF_000009045.1-PMID_12345678",
  release_version: "v0.4.0",
  assembly_accession: "GCF_000009045.1",
  source_id: null,
  asset_kind: "gff3",
  logical_path: browserSource.record_root,
  origin_host: "huggingface.co",
  content_type: "application/gzip",
  byte_size: 100,
  sha256: "c".repeat(64),
  supports_range: 1,
  redistribution_status: "verified_redistributable",
  is_public: 1,
}};
const browserAssets = [
  {{ ...asset, asset_key: "v0.3.0--assembly-GCF_000009045.1--fasta", asset_kind: "fasta", logical_path: "assemblies/GCF_000009045.1/reference/reference.fna", byte_size: 200, sha256: "d".repeat(64) }},
  asset,
  {{ ...asset, asset_key: "v0.3.0--assembly-GCF_000009045.1--gff3", asset_kind: "gff3", logical_path: "assemblies/GCF_000009045.1/reference/genes.gff3.gz", byte_size: 300, sha256: "e".repeat(64) }},
  {{ ...asset, asset_key: "v0.3.0--assembly-GCF_000009045.1--tbi", asset_kind: "tbi", logical_path: "assemblies/GCF_000009045.1/reference/genes.gff3.gz.tbi", byte_size: 400, sha256: "f".repeat(64) }},
  studyGff,
];
const browserContigs = [
  {{ contig_accession: "plasmid_small", length_bp: 12000 }},
  {{ contig_accession: "NC_000964.3", length_bp: 4215606 }},
  {{ contig_accession: "plasmid_equal_a", length_bp: 12000 }},
];
const signalAssets = ["forward", "reverse"].map((strand) => ({{
  ...asset,
  asset_key: `v0.3.0--BATTER_S1_003--signal-${{strand}}`,
  source_id: "BATTER_S1_003",
  asset_kind: "bigwig",
  logical_path: `tracks/BATTER_S1_003/signal.${{strand}}.bw`,
}}));
const db = {{
  prepare(sql) {{
    if (sql.includes("FROM release_versions")) return {{ bind(version) {{ return {{ first: async () => version === release.release_version ? release : null }}; }} }};
    if (sql.startsWith("SELECT * FROM assemblies WHERE")) return {{ bind() {{ return {{ first: async () => browserAssembly }}; }} }};
    if (sql.startsWith("SELECT * FROM tracks WHERE")) return {{ bind() {{ return {{ all: async () => ({{ results: browserTracks }}) }}; }} }};
    if (sql.startsWith("SELECT * FROM sources WHERE")) return {{ bind() {{ return {{ first: async () => browserSource }}; }} }};
    if (sql.startsWith("SELECT contig_accession, length_bp")) return {{ bind() {{ return {{ first: async () => browserContigs.sort((a,b) => b.length_bp-a.length_bp || a.contig_accession.localeCompare(b.contig_accession))[0] }}; }} }};
    if (sql.startsWith("SELECT reference_name, biological_coordinate_1based")) return {{ bind() {{ return {{ first: async () => ({{ reference_name: "NC_000964.3", biological_coordinate_1based: 19000 }}) }}; }} }};
    if (sql.includes("FROM assets")) return {{ bind(...params) {{ return {{ first: async () => params[0] === asset.asset_key && params[1] === asset.release_version ? asset : null, all: async () => ({{ results: params[1] === browserAssembly.accession ? browserAssets : params[1] === browserSource.source_id ? signalAssets : [] }}) }}; }} }};
    if (sql.includes("SELECT release_status")) return {{ bind() {{ return {{ all: async () => ({{ results: [{{ release_status: "published_standardized", total: 24 }}, {{ release_status: "audit_only", total: 1 }}] }}) }}; }} }};
    if (sql.includes("SELECT evidence_class")) return {{ bind() {{ return {{ all: async () => ({{ results: [{{ evidence_class: "author_called_endpoint", total: 1061 }}, {{ evidence_class: "author_reported", total: 28399 }}] }}) }}; }} }};
    if (sql.includes("FROM endpoints WHERE")) return {{ bind() {{ return {{ first: async () => ({{ total: 29460 }}) }}; }} }};
    if (sql.includes("FROM assemblies WHERE")) return {{ bind() {{ return {{ first: async () => ({{ total: 21 }}) }}; }} }};
    if (sql.includes("FROM sources WHERE")) return {{ bind() {{ return {{ first: async () => ({{ total: 24 }}) }}; }} }};
    throw new Error(`Unexpected query: ${{sql}}`);
  }},
}};

let fetchedUrl = null;
const fetchMode = {fetch_mode_js};
const dataReleaseManifestMode = {data_release_manifest_mode_js};
const dataReleaseManifest = {{
  releaseVersion: "v0.4.0",
  assets: {{
    "assemblies/GCF_000009045.1/reference/reference.fna": {{ url: "https://huggingface.co/datasets/liurulong/terminator/resolve/0123456789abcdef0123456789abcdef01234567/v0.3.0/assemblies/GCF_000009045.1/reference/reference.fna", revision: "0123456789abcdef0123456789abcdef01234567", asset_kind: "fasta", byte_size: 200, sha256: "d".repeat(64) }},
    "assemblies/GCF_000009045.1/reference/reference.fna.fai": {{ url: "https://huggingface.co/datasets/liurulong/terminator/resolve/0123456789abcdef0123456789abcdef01234567/v0.3.0/assemblies/GCF_000009045.1/reference/reference.fna.fai", revision: "0123456789abcdef0123456789abcdef01234567", asset_kind: "fai", byte_size: 29, sha256: "b".repeat(64) }},
    "assemblies/GCF_000009045.1/reference/genes.gff3.gz": {{ url: "https://huggingface.co/datasets/liurulong/terminator/resolve/0123456789abcdef0123456789abcdef01234567/v0.3.0/assemblies/GCF_000009045.1/reference/genes.gff3.gz", revision: "0123456789abcdef0123456789abcdef01234567", asset_kind: "gff3", byte_size: 300, sha256: "e".repeat(64) }},
    "assemblies/GCF_000009045.1/reference/genes.gff3.gz.tbi": {{ url: "https://huggingface.co/datasets/liurulong/terminator/resolve/0123456789abcdef0123456789abcdef01234567/v0.3.0/assemblies/GCF_000009045.1/reference/genes.gff3.gz.tbi", revision: "0123456789abcdef0123456789abcdef01234567", asset_kind: "tbi", byte_size: 400, sha256: "f".repeat(64) }},
    "genomes/GCF_000009045.1/studies/PMID_12345678/endpoints.gff3.gz": {{ url: "https://huggingface.co/datasets/liurulong/terminator/resolve/abcdefabcdefabcdefabcdefabcdefabcdefabcd/v0.4.0/genomes/GCF_000009045.1/studies/PMID_12345678/endpoints.gff3.gz", revision: "abcdefabcdefabcdefabcdefabcdefabcdefabcd", asset_kind: "gff3", byte_size: 100, sha256: "c".repeat(64) }},
    "genomes/GCF_000009045.1/metadata.tsv": {{ url: "https://huggingface.co/datasets/liurulong/terminator/resolve/abcdefabcdefabcdefabcdefabcdefabcdefabcd/v0.4.0/genomes/GCF_000009045.1/metadata.tsv", revision: "abcdefabcdefabcdefabcdefabcdefabcdefabcd", asset_kind: "metadata", byte_size: 50, sha256: "a".repeat(64) }},
  }},
}};
globalThis.fetch = async (url) => {{
  fetchedUrl = String(url);
  if (fetchMode === "throw") throw new Error("Network connection lost");
  const body = "NC_000964.3\\t4215606\\t72\\t70\\t71\\n";
  return new Response(body, {{ status: 200, headers: {{ "content-type": "text/plain", "content-length": "29" }} }});
}};
const env = {{
  BTED_DB: db,
  ALLOWED_ORIGIN_HOST: "huggingface.co",
  ASSETS: {{
    async fetch(request) {{
      if (new URL(request.url).pathname !== "/assets/data-release.json") return new Response("missing", {{ status: 404 }});
      if (dataReleaseManifestMode === "missing") return new Response("missing", {{ status: 404 }});
      if (dataReleaseManifestMode === "malformed") return new Response(JSON.stringify({{ ...dataReleaseManifest, assets: {{ ...dataReleaseManifest.assets, "assemblies/GCF_000009045.1/reference/reference.fna.fai": {{ ...dataReleaseManifest.assets["assemblies/GCF_000009045.1/reference/reference.fna.fai"], url: "https://huggingface.co/datasets/liurulong/terminator/resolve/main/v0.3.0/assemblies/GCF_000009045.1/reference/reference.fna.fai" }} }} }}), {{ status: 200 }});
      return new Response(JSON.stringify(dataReleaseManifest), {{ status: 200, headers: {{ "content-type": "application/json" }} }});
    }}
  }},
}};
if ({local_asset_base_js} !== null) env.LOCAL_ASSET_BASE = {local_asset_base_js};
const response = await worker.fetch(
  new Request({request_url_js} + ({request_path_js} ?? ("/api/assets/" + asset.asset_key))),
  env,
);
let body;
try {{ body = await response.clone().json(); }} catch {{ body = await response.text(); }}
process.stdout.write(JSON.stringify({{
  status: response.status,
  body,
  cacheControl: response.headers.get("cache-control"),
  fetchedUrl,
}}));
"""
        result = subprocess.run(
            ["node", "--input-type=module", "-e", script],
            cwd=REPO_ROOT,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        return json.loads(result.stdout)

    def test_loopback_request_can_use_explicit_loopback_asset_base(self):
        payload = self.run_worker(local_asset_base="http://127.0.0.1:8790")
        self.assertEqual(payload["status"], 200)
        self.assertEqual(payload["body"], "NC_000964.3\t4215606\t72\t70\t71\n")
        self.assertEqual(
            payload["fetchedUrl"],
            "http://127.0.0.1:8790/assemblies/GCF_000009045.1/reference/reference.fna.fai",
        )

    def test_non_loopback_request_ignores_local_asset_base(self):
        payload = self.run_worker(
            request_url="https://preview.example.test",
            local_asset_base="http://127.0.0.1:8790",
        )
        self.assertEqual(payload["status"], 200)
        self.assertEqual(
            payload["fetchedUrl"],
            "https://huggingface.co/datasets/liurulong/terminator/resolve/0123456789abcdef0123456789abcdef01234567/v0.3.0/assemblies/GCF_000009045.1/reference/reference.fna.fai",
        )

    def test_missing_or_unpinned_release_manifest_fails_clearly(self):
        missing = self.run_worker(data_release_manifest_mode="missing")
        self.assertEqual(missing["status"], 503)
        self.assertEqual(missing["body"], {"error": "data_release_manifest_missing"})
        self.assertIsNone(missing["fetchedUrl"])

        malformed = self.run_worker(data_release_manifest_mode="malformed")
        self.assertEqual(malformed["status"], 503)
        self.assertEqual(malformed["body"], {"error": "data_release_manifest_invalid"})
        self.assertIsNone(malformed["fetchedUrl"])

    def test_loopback_request_rejects_non_loopback_local_asset_base(self):
        payload = self.run_worker(local_asset_base="http://assets.example.test")
        self.assertEqual(payload["status"], 403)
        self.assertEqual(payload["body"], {"error": "local_origin_not_allowed"})
        self.assertIsNone(payload["fetchedUrl"])

    def test_network_error_becomes_structured_502_without_leaking_opaque_500(self):
        payload = self.run_worker(fetch_mode="throw")
        self.assertEqual(payload["status"], 502)
        self.assertEqual(
            payload["body"],
            {
                "error": "asset_origin_unavailable",
                "asset_key": "v0.4.0--assembly-GCF_000009045.1--fai",
            },
        )
        self.assertEqual(payload["cacheControl"], "no-store")

    def test_current_api_health_and_retired_v1_route(self):
        health = self.run_worker(request_path="/api/health")
        self.assertEqual(health["status"], 200)
        self.assertEqual(health["body"]["status"], "ok")
        self.assertEqual(health["body"]["release"]["release_version"], "v0.4.0")
        self.assertIsNone(health["fetchedUrl"])

        retired = self.run_worker(request_path="/api/v1/health")
        self.assertEqual(retired["status"], 404)

    def test_v02_query_and_asset_route_are_retired(self):
        retired = self.run_worker(request_path="/api/health?release_version=v0.2.0")
        self.assertEqual(retired["status"], 410)
        self.assertEqual(retired["body"], {
            "error": "release_version_retired",
            "release_version": "v0.2.0",
            "current_release_version": "v0.4.0",
            "archive_path": "data/archive/BTED-v0.2.0.tar.gz",
        })
        self.assertIsNone(retired["fetchedUrl"])

        old_download = self.run_worker(
            request_path="/downloads/v0.2.0/records/BATTER_S1_003/endpoints.bed",
        )
        self.assertEqual(old_download["status"], 410)
        self.assertEqual(old_download["body"]["error"], "release_version_retired")
        self.assertEqual(old_download["body"]["archive_path"], "data/archive/BTED-v0.2.0.tar.gz")
        self.assertIsNone(old_download["fetchedUrl"])

        old_asset = self.run_worker(request_path="/api/assets/v0.2.0--assembly-GCF_000009045.1--fai")
        self.assertEqual(old_asset["status"], 404)
        self.assertEqual(old_asset["body"]["error"], "unknown_or_private_asset")
        self.assertIsNone(old_asset["fetchedUrl"])

    def test_jbrowse_config_uses_v04_genome_study_gff3_and_v03_reference_assets(self):
        payload = self.run_worker(
            request_url="https://preview.example.test",
            request_path="/api/assemblies/GCF_000009045.1/jbrowse-config",
        )
        self.assertEqual(payload["status"], 200)
        config = payload["body"]
        self.assertEqual(config["metadata"]["release_version"], "v0.4.0")
        self.assertEqual(config["defaultSession"]["views"][0]["displayedRegions"][0]["refName"], "NC_000964.3")
        self.assertEqual(config["defaultSession"]["name"], "BTED · GCF_000009045.1")
        self.assertEqual(config["plugins"][0]["name"], "BTEDTrackPlugin")
        self.assertEqual(config["plugins"][0]["esmUrl"], "https://preview.example.test/jbrowse/plugins/bted-track-plugin.js")
        endpoint_track = next(track for track in config["tracks"] if track["trackId"].startswith("source_"))
        expected_gff3 = "https://huggingface.co/datasets/liurulong/terminator/resolve/abcdefabcdefabcdefabcdefabcdefabcdefabcd/v0.4.0/genomes/GCF_000009045.1/studies/PMID_12345678/endpoints.gff3.gz"
        self.assertEqual(endpoint_track["adapter"]["type"], "Gff3Adapter")
        self.assertEqual(endpoint_track["adapter"]["gffLocation"]["uri"], expected_gff3)
        self.assertEqual(endpoint_track["metadata"]["GFF3_download"], expected_gff3)
        self.assertEqual(endpoint_track["metadata"]["source_ids"], ["BATTER_S1_003"])
        self.assertEqual(endpoint_track["metadata"]["btedAbout"]["authors"], "A Researcher; B Researcher")
        self.assertNotIn("license", endpoint_track["metadata"]["btedAbout"])
        self.assertEqual(endpoint_track["metadata"]["btedDownloads"][0]["kind"], "endpoint")
        self.assertEqual(endpoint_track["displays"][0]["renderer"]["color1"], "jexl:btedStrandColor(feature)")
        self.assertGreaterEqual(endpoint_track["displays"][0]["height"], 60)
        signal_track = next(track for track in config["tracks"] if track["type"] == "MultiQuantitativeTrack")
        self.assertTrue(signal_track["metadata"]["btedMirroredSignal"])
        self.assertEqual(signal_track["adapter"]["type"], "MultiWiggleAdapter")
        self.assertEqual(
            [(item["source"], item["color"]) for item in signal_track["adapter"]["subadapters"]],
            [("plus", "#0f766e"), ("minus", "#be123c")],
        )
        self.assertIn("+ / −", signal_track["metadata"]["btedAbout"]["strand"])
        self.assertTrue(any(row["configuration"] == signal_track["trackId"] for row in config["defaultSession"]["views"][0]["tracks"]))
        self.assertNotIn("BED_download", endpoint_track["metadata"])
        self.assertIsNone(payload["fetchedUrl"])
        reference_track = next(track for track in config["tracks"] if track["trackId"].endswith("_genes"))
        self.assertEqual(reference_track["adapter"]["gffGzLocation"]["uri"], "https://preview.example.test/api/assets/v0.3.0--assembly-GCF_000009045.1--gff3")
        self.assertEqual(reference_track["displays"][0]["renderer"]["color1"], "jexl:btedStrandColor(feature)")
        self.assertEqual(reference_track["displays"][0]["renderer"]["color2"], "jexl:btedStrandColor(feature)")
        self.assertGreater(reference_track["displays"][0]["height"], endpoint_track["displays"][0]["height"])

    def test_stats_keeps_release_and_source_status_counts(self):
        payload = self.run_worker(request_path="/api/stats")
        self.assertEqual(payload["status"], 200)
        self.assertEqual(payload["body"]["release"]["release_version"], "v0.4.0")
        self.assertEqual(payload["body"]["sources"], {
            "total": 25,
            "published_standardized": 24,
            "audit_only": 1,
        })
        self.assertEqual(payload["body"]["endpoints"]["total"], 29460)
        self.assertEqual(payload["body"]["assemblies"]["total"], 21)
        self.assertNotIn("augmentation", payload["body"])

    def test_augmentation_api_route_is_removed(self):
        response = self.run_worker(request_path="/api/augmentation")
        self.assertEqual(response["status"], 404)
        self.assertEqual(response["body"]["error"], "not_found")


if __name__ == "__main__":
    unittest.main()
