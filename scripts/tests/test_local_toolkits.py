import importlib.util
import json
from pathlib import Path
from unittest import TestCase
from unittest.mock import Mock, patch

SCRIPT = Path(__file__).resolve().parents[1] / "validate_local_toolkits.py"
spec = importlib.util.spec_from_file_location("toolkit_validation", SCRIPT)
assert spec and spec.loader
validation = importlib.util.module_from_spec(spec)
spec.loader.exec_module(validation)


class ToolkitGuardTests(TestCase):
    def test_multiple_filter_logs_do_not_multiply_the_actual_document(self):
        samples = [
            {"doc_id": 0, "resps": [["synthetic answer"]]},
            {"doc_id": 0, "resps": [["synthetic answer"]]},
        ]
        self.assertEqual(
            validation.verify_benchmark_sample_logs(samples), "synthetic answer"
        )

    def test_missing_extra_or_inconsistent_sample_responses_fail(self):
        for samples in (
            [],
            [{"doc_id": 0, "resps": [[""]]}],
            [{"doc_id": 0, "resps": [["one"]]}, {"doc_id": 1, "resps": [["one"]]}],
            [
                {"doc_id": 0, "resps": [["one"]]},
                {"doc_id": 0, "resps": [["different"]]},
            ],
        ):
            with self.subTest(samples=samples), self.assertRaises(ValueError):
                validation.verify_benchmark_sample_logs(samples)

    def test_only_explicit_owned_endpoints_are_accepted(self):
        for host in ("localhost", "127.0.0.1", "llmserving-ci-toolkit-ollama"):
            with self.subTest(host=host), patch.dict(
                "os.environ",
                {
                    "APP_ENV": "test",
                    "AUTH_MODE": "local-demo",
                    "LIVE_MODEL_URL": f"http://{host}:11434",
                },
                clear=True,
            ):
                self.assertEqual(
                    validation.require_local_test_endpoint(), f"http://{host}:11434"
                )

    def test_remote_cloud_credential_and_nonroot_urls_fail(self):
        for url in (
            "http://external.example:11434",
            "https://localhost:11434",
            "http://localhost:11434/v1",
            "http://user:password@localhost:11434",
            "http://localhost:11434?query=1",
            "http://localhost:11434#fragment",
            "",
        ):
            with self.subTest(url=url), patch.dict(
                "os.environ",
                {"APP_ENV": "test", "AUTH_MODE": "local-demo", "LIVE_MODEL_URL": url},
                clear=True,
            ), self.assertRaises(ValueError):
                validation.require_local_test_endpoint()
        for field, value in (("APP_ENV", "production"), ("AUTH_MODE", "entra")):
            with self.subTest(field=field), patch.dict(
                "os.environ",
                {
                    "APP_ENV": "test",
                    "AUTH_MODE": "local-demo",
                    "LIVE_MODEL_URL": "http://localhost:11434",
                    field: value,
                },
                clear=True,
            ), self.assertRaises(ValueError):
                validation.require_local_test_endpoint()

    def test_only_real_pinned_tool_provenance_is_accepted(self):
        for source, commit in (
            ("https://github.com/ray-project/llmperf.git", validation.LLMPERF_COMMIT),
            ("https://github.com/ray-project/llmperf.git", "different"),
            ("https://example.com/fake.git", validation.LLMPERF_COMMIT),
            ("https://pypi.org/llmperf", None),
        ):
            payload = {"url": source, "vcs_info": {"commit_id": commit}}
            with self.subTest(source=source, commit=commit), patch.object(
                validation,
                "distribution",
                return_value=Mock(read_text=Mock(return_value=json.dumps(payload))),
            ):
                if (
                    source.endswith("ray-project/llmperf.git")
                    and commit == validation.LLMPERF_COMMIT
                ):
                    self.assertEqual(validation.verify_llmperf_provenance(), payload)
                else:
                    with self.assertRaises(ValueError):
                        validation.verify_llmperf_provenance()
