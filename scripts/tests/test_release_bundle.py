from __future__ import annotations

from scripts.tests import operator_fixture  # noqa: F401

import copy
import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "release_bundle", ROOT / "scripts/release_bundle.py"
)
bundle = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bundle)


class ReleaseBundleTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.archives = self.root / "archives"
        self.records = self.root / "records"
        self.archives.mkdir()
        self.records.mkdir()
        self.environment = {
            "GITHUB_REPOSITORY": "example/llmserving",
            "GITHUB_REF": "refs/heads/main",
            "GITHUB_EVENT_NAME": "workflow_dispatch",
            "GITHUB_SHA": "a" * 40,
            "GITHUB_RUN_ID": "123",
            "GITHUB_RUN_ATTEMPT": "1",
        }
        environment = patch.dict(os.environ, self.environment, clear=True)
        environment.start()
        self.addCleanup(environment.stop)
        for component in bundle.COMPONENTS:
            path = self.archives / bundle.archive_name(component)
            path.write_bytes(f"synthetic test archive: {component}".encode())
            record = bundle.record_archive(
                component,
                path,
                "sha256:" + "b" * 64 if component in bundle.IMAGES else None,
            )
            (self.records / f"{component}.json").write_text(json.dumps(record))

    def record(self, component="backend"):
        return json.loads((self.records / f"{component}.json").read_text())

    def test_complete_run_bound_manifest_and_archive_verification(self):
        manifest = bundle.assemble(self.records)
        self.assertEqual(len(manifest["artifacts"]), 8)
        self.assertEqual(manifest["sourceSha"], "a" * 40)
        self.assertEqual(manifest["runId"], "123")
        self.assertEqual(manifest["runAttempt"], "1")
        self.assertIn("NOT registry pull digests", manifest["limitations"][0])
        bundle.verify(manifest, self.archives)

    def test_packaging_refuses_other_repos_refs_events_and_missing_context(self):
        for field in self.environment:
            for value in (None, "invalid"):
                environment = dict(self.environment)
                if value is None:
                    environment.pop(field)
                else:
                    environment[field] = value
                with self.subTest(field=field, value=value), patch.dict(
                    os.environ, environment, clear=True
                ), self.assertRaises(ValueError):
                    bundle.context()

    def test_manifest_requires_exactly_every_component_record(self):
        (self.records / "backend.json").unlink()
        with self.assertRaises(ValueError):
            bundle.assemble(self.records)
        (self.records / "foreign.json").write_text("{}")
        with self.assertRaises(ValueError):
            bundle.assemble(self.records)

    def test_mixed_source_run_attempt_or_component_is_rejected(self):
        for field, value in (
            ("sourceSha", "c" * 40),
            ("runId", "124"),
            ("runAttempt", "2"),
            ("repository", "other/repo"),
            ("component", "frontend"),
            ("schemaVersion", True),
        ):
            record = self.record()
            record[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                bundle.validate_record(record, "backend", bundle.context())

    def test_records_reject_unexpected_fields_paths_sizes_and_digests(self):
        for field, value in (
            ("unexpected", True),
            ("archive", "../backend.tar.gz"),
            ("sizeBytes", True),
            ("sizeBytes", 0),
            ("sizeBytes", "10"),
            ("sha256", "z" * 64),
            ("sha256", "b" * 63),
            ("imageConfigDigest", "sha256:wrong"),
            ("imageConfigDigest", None),
        ):
            record = self.record()
            record[field] = value
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                bundle.validate_record(record, "backend", bundle.context())
        record = self.record()
        record.pop("imageConfigDigest")
        with self.assertRaises(ValueError):
            bundle.validate_record(record, "backend", bundle.context())

    def test_manifest_rejects_duplicate_missing_unknown_or_mixed_run_artifacts(self):
        complete = bundle.assemble(self.records)
        for mutation in ("duplicate", "missing", "unknown", "mixed", "root-run"):
            manifest = copy.deepcopy(complete)
            if mutation == "duplicate":
                manifest["artifacts"][-1] = manifest["artifacts"][0]
            elif mutation == "missing":
                manifest["artifacts"].pop()
            elif mutation == "unknown":
                manifest["artifacts"][0]["component"] = "foreign"
            elif mutation == "mixed":
                manifest["artifacts"][0]["runId"] = "999"
            else:
                manifest["runId"] = "999"
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                bundle.verify(manifest, self.archives)

    def test_changed_same_size_or_truncated_archive_fails_verification(self):
        manifest = bundle.assemble(self.records)
        path = self.archives / "backend.tar.gz"
        data = path.read_bytes()
        for replacement in (b"x" * len(data), data[:-1], b""):
            path.write_bytes(replacement)
            with self.subTest(size=len(replacement)), self.assertRaises(ValueError):
                bundle.verify(manifest, self.archives)
        path.unlink()
        with self.assertRaises((ValueError, OSError)):
            bundle.verify(manifest, self.archives)

    def test_symlink_records_and_archives_are_rejected(self):
        path = self.archives / "backend.tar.gz"
        path.unlink()
        path.symlink_to(self.archives / "frontend.tar.gz")
        with self.assertRaises(ValueError):
            bundle.record_archive("backend", path, "sha256:" + "b" * 64)
        record = self.records / "backend.json"
        record.unlink()
        record.symlink_to(self.records / "frontend.json")
        with self.assertRaises(ValueError):
            bundle.assemble(self.records)

    def test_functions_cannot_claim_image_digest_and_filename_is_fixed(self):
        path = self.archives / "functions.zip"
        with self.assertRaises(ValueError):
            bundle.record_archive("functions", path, "sha256:" + "b" * 64)
        with self.assertRaises(ValueError):
            bundle.record_archive("backend", path, "sha256:" + "b" * 64)
        with self.assertRaises(ValueError):
            bundle.archive_name("foreign")

    def test_workflow_opt_in_has_no_azure_or_registry_credentials(self):
        source = (ROOT / ".github/workflows/runtime-ci.yml").read_text()
        self.assertIn("package_release:", source)
        self.assertIn("default: false", source)
        self.assertIn(
            """LLM_SERVING_OPERATOR_CONFIG: '{"repository":${{ toJSON(github.repository) }}}'""",
            source,
        )
        self.assertNotIn("vars.AZURE_OPERATOR_REPOSITORY", source)
        self.assertIn(
            "needs: [real-local-api, jobs, functions, mocked-browser, images]", source
        )
        self.assertIn("pattern: release-record-*-${{ github.run_attempt }}", source)
        self.assertNotIn("id-token: write", source)
        self.assertNotIn("packages: write", source)
        self.assertNotIn("secrets.", source)
        self.assertNotIn("docker push", source)
        self.assertLess(
            source.index("Smoke real image runtime imports or HTTP"),
            source.index("Export the exact checked image"),
        )
        for section in (
            source.split("Record checked Functions candidate checksum", 1)[1],
            source.split("Export the exact checked image", 1)[1],
            source.split("\n  release-manifest:", 1)[1],
        ):
            self.assertIn("github.event_name == 'workflow_dispatch'", section)
            self.assertIn("github.ref == 'refs/heads/main'", section)
            self.assertIn("inputs.package_release", section)

    def test_frontend_build_uses_bounded_install_and_local_tools(self):
        source = (ROOT / "frontend/Dockerfile").read_text()
        self.assertIn("--fetch-retries=2 --fetch-timeout=30000", source)
        self.assertIn("test -x node_modules/.bin/tsc", source)
        self.assertIn("test -x node_modules/.bin/vite", source)
        self.assertIn("./node_modules/.bin/tsc --noEmit", source)
        self.assertIn("./node_modules/.bin/vite build", source)
        self.assertNotIn("npx ", source)
        workflow = (ROOT / ".github/workflows/runtime-ci.yml").read_text()
        self.assertIn(
            "timeout-minutes: ${{ matrix.image == 'frontend' && 10 || 45 }}",
            workflow,
        )


if __name__ == "__main__":
    unittest.main()
