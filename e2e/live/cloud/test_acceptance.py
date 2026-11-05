"""Offline contract tests only: these are NOT evidence of a cloud deployment."""
import copy
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

SPEC = importlib.util.spec_from_file_location("acceptance", Path(__file__).with_name("acceptance.py"))
live = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(live)


def config():
    return {
        "apiUrl": "https://main.contoso.net/api",
        "environmentId": "acceptance", "catalogEntryId": "model",
        "engineId": "vllm", "modelRepo": "org/model", "checkpointRef": "a" * 40,
        "deployedSourceCommit": "b" * 40, "deploymentEvidence": "deployment-run-123",
        "requestTimeoutSeconds": 1, "operationTimeoutSeconds": 1, "pollSeconds": 0.1,
        "allowConfigWrites": True, "allowDeploy": True, "seededWorkloadsVerified": True,
        "golden": {"id": "golden", "version": 1, "caseCount": 12, "minPassRate": 1},
        "performance": {
            mode: {"maxP95LatencyMs": 100, "minTokensPerSecond": 10, "maxFailureRate": 0}
            for mode in ("single", "concurrent")
        },
    }


class APIStub:
    """Deliberately offline transport for contract tests, never imported by the runner."""
    def __init__(self, replies):
        self.replies, self.calls = replies, []

    def call(self, method, path, body=None, **kwargs):
        self.calls.append((method, path, body, kwargs))
        reply = self.replies[(method, path)]
        if isinstance(reply, Exception):
            raise reply
        return copy.deepcopy(reply)


def harness(api=None):
    evidence = {"checks": [], "resources": {"runs": []}}
    return live.Acceptance(config(), api, evidence, lambda: None)


class AcceptanceContracts(unittest.TestCase):
    def test_explicit_cloud_urls_only(self):
        for value in ("http://main.contoso.net", "https://localhost", "https://127.0.0.1",
                      "https://10.0.0.1", "https://[::1]", "https://x.invalid",
                      "https://user:pass@main.contoso.net", "https://main.contoso.net?token=x"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                live.cloud_url(value)
        self.assertEqual(live.cloud_url("https://main.contoso.net/api/"),
                         "https://main.contoso.net/api")

    def test_nonfinite_and_boolean_thresholds_rejected(self):
        for value in (None, True, float("nan"), float("inf"), -1):
            with self.subTest(value=value), self.assertRaises(ValueError):
                live.number(value, "threshold", 0, 100)

    def test_missing_model_pin_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            payload = config()
            payload["checkpointRef"] = "main"
            path.write_text(json.dumps(payload))
            with self.assertRaises(ValueError):
                live.load_config(path)

    def test_gpu_requires_explicit_thresholds(self):
        payload = config()
        payload["performance"]["single"]["maxP95LatencyMs"] = None
        with self.assertRaises(ValueError):
            live.validate_gpu(payload)

    def test_api_records_actual_error_and_never_uses_demo_identity(self):
        exchanges = []
        api = live.API(config(), "actual-token", exchanges)
        error = HTTPError(
            config()["apiUrl"] + "/providers", 403, "Forbidden",
            {"x-request-id": "actual-request"}, io.BytesIO(b'{"error":"forbidden_domain"}'),
        )
        with patch.object(api.opener, "open", side_effect=error) as opened:
            with self.assertRaisesRegex(AssertionError, "403.*forbidden_domain"):
                api.call("GET", "/providers")
        request = opened.call_args.args[0]
        self.assertEqual(request.get_header("Authorization").split(), ["Bearer", api.token])
        api.token = "different-configured-operator-token"
        with patch.object(api.opener, "open", side_effect=URLError("offline")) as opened_again:
            with self.assertRaises(URLError):
                api.call("GET", "/providers")
        second_request = opened_again.call_args.args[0]
        self.assertEqual(second_request.get_header("Authorization").split(), ["Bearer", api.token])
        self.assertIsNone(request.get_header("X-demo-user"))
        self.assertEqual(exchanges[0]["status"], 403)
        self.assertEqual(exchanges[0]["requestId"], "actual-request")
        self.assertEqual(exchanges[0]["body"], '{"error":"forbidden_domain"}')

    def test_nonfinite_json_never_corrupts_evidence(self):
        with self.assertRaisesRegex(ValueError, "Non-finite"):
            live.parse_json('{"throughput": NaN}')

    def test_missing_config_writes_permission_never_mutates(self):
        subject = harness(APIStub({}))
        subject.c["allowConfigWrites"] = False
        self.assertFalse(subject.check("db", subject.configurations))
        self.assertEqual(subject.e["checks"][0]["status"], "blocked")
        self.assertEqual(subject.api.calls, [])

    def test_unsupported_cleanup_is_failed_not_fake_success(self):
        subject = harness(APIStub({
            ("DELETE", "/environments/acceptance/model-configurations/m"):
                AssertionError("HTTP 405: cleanup endpoint unavailable"),
        }))
        subject.e["resources"]["scratch"] = {"model": {"modelConfigId": "m"}}
        self.assertFalse(subject.check("cleanup", subject.cleanup))
        self.assertEqual(subject.e["checks"][0]["status"], "failed")
        self.assertIn("405", subject.e["checks"][0]["error"])

    def test_finally_cleans_partial_probe_after_inference_create_failure(self):
        subject = harness(APIStub({
            ("POST", "/environments/acceptance/model-configurations"): {"modelConfigId": "m"},
            ("POST", "/environments/acceptance/inference-configurations"):
                AssertionError("actual inference write error"),
            ("DELETE", "/environments/acceptance/model-configurations/m"): None,
            ("GET", "/environments/acceptance/model-configurations"): {"items": []},
        }))
        with patch.object(live.Acceptance, "health", return_value={}):
            with patch.object(live.Acceptance, "environment", return_value={}):
                live.execute(subject.c, subject.api, subject.e, lambda: None, "control")
        checks = {check["name"]: check for check in subject.e["checks"]}
        self.assertEqual(checks["configuration-db-roundtrip"]["status"], "failed")
        self.assertEqual(checks["configuration-cleanup"]["status"], "passed")
        self.assertEqual(subject.e["resources"]["scratch"]["deletedIds"], ["m"])

    def test_cleanup_attempts_both_exact_owned_ids_and_verifies_absence(self):
        subject = harness(APIStub({
            ("DELETE", "/environments/acceptance/inference-configurations/i"):
                AssertionError("HTTP 409: in use"),
            ("DELETE", "/environments/acceptance/model-configurations/m"): None,
            ("GET", "/environments/acceptance/model-configurations"): {"items": []},
        }))
        subject.e["resources"]["scratch"] = {
            "model": {"modelConfigId": "m"}, "inference": {"inferenceConfigId": "i"},
        }
        self.assertFalse(subject.check("cleanup", subject.cleanup))
        self.assertEqual(subject.e["resources"]["scratch"]["deletedIds"], ["m"])
        self.assertIn("409", subject.e["checks"][0]["error"])

    def test_delete_204_empty_body_is_valid(self):
        api = live.API(config(), "operator-token", [])
        response = HTTPError(config()["apiUrl"], 204, "No Content", {}, io.BytesIO(b""))
        with patch.object(api.opener, "open", return_value=response):
            self.assertIsNone(api.call("DELETE", "/owned-exact-id", expected=204))

    def test_successful_config_db_roundtrip_uses_real_api_wire_shapes(self):
        model = {
            "modelConfigId": "m", "catalogEntryId": "model",
            "resolvedCheckpointRef": "a" * 40, "modelSettings": {}, "version": 1,
        }
        inference = {
            "inferenceConfigId": "i", "engineId": "vllm",
            "servingSettings": {}, "generationSettings": {}, "version": 1,
        }
        api = APIStub({
            ("POST", "/environments/acceptance/model-configurations"): model,
            ("POST", "/environments/acceptance/inference-configurations"): inference,
            ("GET", "/environments/acceptance/model-configurations"): {"items": [model]},
            ("GET", "/environments/acceptance/inference-configurations"): {"items": [inference]},
        })
        subject = harness(api)
        self.assertEqual(subject.configurations(), {
            "modelConfigId": "m", "inferenceConfigId": "i",
        })
        self.assertEqual(api.calls[0][2]["resolvedCheckpointRef"], "a" * 40)
        self.assertEqual(subject.e["resources"]["scratch"]["model"], model)
        self.assertEqual(len(api.calls), 4)

    def test_missing_api_catalog_row_records_failure(self):
        with self.assertRaisesRegex(AssertionError, "absent"):
            live.find([], "id", "missing")

    def test_failed_gpu_does_not_remove_cpu_evidence(self):
        subject = harness()
        self.assertTrue(subject.check("health", lambda: {"database": "ready"}))
        self.assertFalse(subject.check("deploy", lambda: live.require(False, "real error")))
        self.assertEqual([row["status"] for row in subject.e["checks"]], ["passed", "failed"])
        self.assertIn("real error", subject.e["checks"][1]["error"])

    def test_timeout_keeps_actual_last_response(self):
        subject = harness(APIStub({("GET", "/operation"): {"status": "running"}}))
        with patch.object(live.time, "monotonic", side_effect=[0, 2]):
            with self.assertRaisesRegex(TimeoutError, "running"):
                subject.poll("/operation", "status", "completed", {"failed"})

    def test_timeout_requests_cancel_and_preserves_run_id(self):
        api = APIStub({
            ("POST", "/environments/acceptance/runs"): {"runId": "run-1"},
            ("POST", "/environments/acceptance/runs/run-1/cancel"): {"status": "running"},
        })
        subject = harness(api)
        with patch.object(subject, "poll", side_effect=TimeoutError("deadline")):
            with self.assertRaises(TimeoutError):
                subject.run("performance", "workload")
        self.assertEqual(subject.e["resources"]["runs"][0]["runId"], "run-1")
        self.assertEqual(subject.e["resources"]["runs"][0]["cancellation"], {"status": "running"})

    def test_golden_historical_twelve_is_not_accepted_without_actual_cases(self):
        subject = harness(APIStub({
            ("GET", "/golden-datasets"): {"goldenDatasets": [{
                "goldenDatasetId": "golden", "version": 1, "reviewStatus": "reviewed",
                "caseCount": 12,
            }]},
        }))
        with patch.object(subject, "run", return_value={"quality": {
            "cases": [], "aggregate": {"totalCases": 12, "passRate": 1},
        }}):
            with self.assertRaisesRegex(AssertionError, "Missing golden case"):
                subject.golden()

    def test_performance_measures_real_thresholds_and_failure_counts(self):
        subject = harness(APIStub({
            ("GET", "/performance-workloads"): {"performanceWorkloads": [{
                "workloadId": "llmperf-single-stream-v1", "version": 1, "concurrency": 1,
            }]},
        }))
        report = {"performance": {
            "runner": "llmperf",
            "testConditions": {
                "concurrency": 1, "durationOrRequestCount": {"requestCount": 25},
                "safetyLimits": {"maxRequests": 40, "maxConcurrency": 1, "timeoutSeconds": 600},
            },
            "units": {"endToEndLatencyMs": "ms", "throughputTokensPerSec": "tokens/sec"},
            "metrics": {"endToEndLatencyMs": {"p95": 100}, "throughputTokensPerSec": 10},
            "requestFailures": {"total": 25, "count": 0, "rate": 0},
        }}
        with patch.object(subject, "run", return_value=report):
            self.assertEqual(subject.performance("single"), report)
            report["performance"]["metrics"]["endToEndLatencyMs"]["p95"] = 100.01
            with self.assertRaisesRegex(AssertionError, "P95"):
                subject.performance("single")
            report["performance"]["metrics"]["endToEndLatencyMs"]["p95"] = 100
            report["performance"]["requestFailures"]["count"] = 1
            with self.assertRaisesRegex(AssertionError, "Inconsistent"):
                subject.performance("single")

    def test_persistence_requires_exact_reports_not_just_http_success(self):
        subject = harness(APIStub({
            ("GET", "/environments/acceptance/model-configurations"): {"items": [{
                "modelConfigId": "m", "version": 1,
            }]},
            ("GET", "/environments/acceptance/inference-configurations"): {"items": [{
                "inferenceConfigId": "i", "version": 1,
            }]},
            ("GET", "/environments/acceptance/runs"): {"runs": [{"runId": "r"}]},
            ("GET", "/environments/acceptance/runs/r"): {"runId": "r", "status": "completed"},
            ("GET", "/environments/acceptance/runs/r/report"): {"runId": "r", "quality": "changed"},
        }))
        resources = {
            "model": {"modelConfigId": "m", "version": 1},
            "inference": {"inferenceConfigId": "i", "version": 1},
            "runs": [{"runId": "r", "run": {"runId": "r", "status": "completed"},
                      "report": {"runId": "r", "quality": "original"}}],
        }
        with self.assertRaisesRegex(AssertionError, "Persisted report changed"):
            subject.persistence(resources)

    def test_redirect_is_refused_before_token_can_be_forwarded(self):
        with self.assertRaisesRegex(RuntimeError, "Redirect refused"):
            live.NoRedirect().redirect_request(None, None, 302, "", {}, "https://elsewhere.net")

    def test_missing_token_exits_blocked_writes_evidence_without_network(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            (path / "config.json").write_text(json.dumps(config()))
            with patch.dict(os.environ, {"LIVE_OPERATOR_TOKEN": ""}):
                with patch.object(live.API, "call", side_effect=AssertionError("network forbidden")):
                    result = live.main([
                        "--config", str(path / "config.json"),
                        "--evidence", str(path / "evidence.json"),
                    ])
            evidence = json.loads((path / "evidence.json").read_text())
            self.assertEqual(result, 2)
            self.assertEqual(evidence["status"], "blocked")
            self.assertFalse(evidence["fullAcceptance"])
            self.assertEqual(evidence["exchanges"], [])


if __name__ == "__main__":
    unittest.main()
