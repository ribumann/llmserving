#!/usr/bin/env python3
"""Real-cloud API acceptance. No server, mocks, provisioning, or Azure credentials."""
from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import math
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


class Blocked(RuntimeError):
    pass


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def number(value, name, minimum, maximum):
    if (
        isinstance(value, bool) or not isinstance(value, (int, float))
        or not math.isfinite(value) or not minimum <= value <= maximum
    ):
        raise ValueError(f"{name} must be finite and between {minimum} and {maximum}")
    return value


def parse_json(text):
    def reject_constant(value):
        raise ValueError(f"Non-finite JSON constant: {value}")
    return json.loads(text, parse_constant=reject_constant)


def read_json(path):
    return parse_json(path.read_text())


def find(rows, key, value):
    for row in rows:
        if row.get(key) == value:
            return row
    raise AssertionError(f"{key}={value!r} absent from actual API response")


def cloud_url(value):
    url = urlsplit(value)
    if (
        url.scheme != "https" or not url.hostname or url.username or url.password
        or url.query or url.fragment or url.hostname in {"localhost"}
        or url.hostname.endswith((".localhost", ".local", ".test", ".invalid", ".example"))
    ):
        raise ValueError("apiUrl must be an explicit deployed HTTPS URL without credentials/query")
    try:
        address = ipaddress.ip_address(url.hostname)
    except ValueError:
        address = None
    if address is not None and not address.is_global:
        raise ValueError("apiUrl cannot be a loopback/private IP")
    return value.rstrip("/")


def load_config(path):
    config = read_json(path)
    cloud_url(config["apiUrl"])
    for key in ("environmentId", "catalogEntryId", "engineId", "checkpointRef",
                "modelRepo", "deployedSourceCommit", "deploymentEvidence"):
        if not isinstance(config.get(key), str) or not config[key].strip():
            raise ValueError(f"{key} must be explicitly supplied")
    if config["engineId"] != "vllm":
        raise ValueError("main cloud acceptance requires the real Azure/vLLM engine")
    if not re.fullmatch(r"[a-fA-F0-9]{40}", config["deployedSourceCommit"]):
        raise ValueError("deployedSourceCommit must be a full Git SHA")
    if not re.fullmatch(r"[a-fA-F0-9]{40}", config["checkpointRef"]):
        raise ValueError("checkpointRef must pin the actual model commit, not a mutable branch")
    number(config["requestTimeoutSeconds"], "requestTimeoutSeconds", 1, 120)
    number(config["operationTimeoutSeconds"], "operationTimeoutSeconds", 1, 1800)
    number(config["pollSeconds"], "pollSeconds", 0.1, 30)
    return config


def validate_gpu(config):
    golden = config["golden"]
    require(isinstance(golden["id"], str) and golden["id"], "Golden ID required")
    for key in ("version", "caseCount"):
        require(type(golden[key]) is int and golden[key] > 0, f"Golden {key} must be positive")
    number(golden["minPassRate"], "minPassRate", 0.001, 1)
    for mode in ("single", "concurrent"):
        policy = config["performance"][mode]
        number(policy["maxP95LatencyMs"], "maxP95LatencyMs", 0.001, 600_000)
        number(policy["minTokensPerSecond"], "minTokensPerSecond", 0.001, 1_000_000)
        number(policy["maxFailureRate"], "maxFailureRate", 0, 0.1)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise RuntimeError(f"Redirect refused ({code}); supply the actual API URL")


class API:
    def __init__(self, config, token, exchanges):
        self.config, self.token, self.exchanges = config, token, exchanges
        self.opener = build_opener(NoRedirect())

    def call(self, method, path, body=None, *, authenticated=True, expected=200):
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        if authenticated:
            headers["Authorization"] = f"Bearer {self.token}"
        request = Request(
            self.config["apiUrl"] + path, method=method, headers=headers,
            data=json.dumps(body).encode() if body is not None else None,
        )
        started = time.monotonic()
        try:
            response = self.opener.open(
                request, timeout=self.config["requestTimeoutSeconds"],
            )
        except HTTPError as error:
            response = error
        with response:
            text = response.read(2_000_001).decode("utf-8", errors="replace")
            exchange = {
                "method": method, "path": path, "status": response.code,
                "elapsedMs": round((time.monotonic() - started) * 1000, 3),
                "requestId": response.headers.get("x-request-id"),
                "body": text,
            }
        self.exchanges.append(exchange)
        require(response.code == expected,
                f"{method} {path}: expected HTTP {expected}, got {response.code}: {text}")
        require(len(text) <= 2_000_000, "API response exceeded evidence size limit")
        if response.code == 204:
            return None
        return parse_json(text)


def stable(payload):
    return {key: value for key, value in payload.items() if key != "requestId"}


class Acceptance:
    def __init__(self, config, api, evidence, persist):
        self.c, self.api, self.e, self.persist = config, api, evidence, persist
        self.root = "/environments/" + quote(config["environmentId"], safe="")

    def check(self, name, action):
        result = {"name": name, "startedAt": datetime.now(timezone.utc).isoformat()}
        self.e["checks"].append(result)
        try:
            result["details"] = action()
            result["status"] = "passed"
        except Blocked as error:
            result.update(status="blocked", error=str(error))
        except (AssertionError, KeyError, TypeError, ValueError, RuntimeError, OSError, URLError) as error:
            result.update(status="failed", error=f"{type(error).__name__}: {error}")
        self.persist()
        return result["status"] == "passed"

    def poll(self, path, key, success, failures):
        deadline = time.monotonic() + self.c["operationTimeoutSeconds"]
        while True:
            payload = self.api.call("GET", path)
            if payload[key] == success:
                return payload
            require(payload[key] not in failures, f"Operation failed: {payload}")
            if time.monotonic() >= deadline:
                raise TimeoutError(f"Operation exceeded deadline; last response: {payload}")
            time.sleep(self.c["pollSeconds"])

    def health(self):
        health = self.api.call("GET", "/healthz", authenticated=False)
        ready = self.api.call("GET", "/readyz", authenticated=False)
        require(health["status"] == "ok", "Health status is not ok")
        require(ready["database"] == "ready", "Database is not ready")
        self.api.call("GET", "/providers", authenticated=False, expected=401)
        self.api.call("GET", "/providers")
        return {"health": health, "readiness": ready, "anonymousRejected": True}

    def environment(self):
        environment = self.api.call("GET", self.root)
        require(environment["context"]["provider"] == "azure", "Not an Azure environment")
        require(environment["context"]["region"].lower() == "italynorth", "Not main ItalyNorth")
        catalog = self.api.call("GET", "/catalog")["catalog"]
        entry = find(catalog, "catalogEntryId", self.c["catalogEntryId"])
        require(entry["huggingFaceRepoId"] == self.c["modelRepo"], "Model repository mismatch")
        require(not entry["isGated"], "Gated models require a separately authorized credential path")
        return {"environment": environment, "catalogEntry": entry}

    def configurations(self):
        if self.c.get("allowConfigWrites") is not True:
            raise Blocked("Explicit allowConfigWrites=true and a dedicated environment required")
        scratch = self.e["resources"].setdefault("scratch", {})
        self.create_configurations(scratch)
        self.verify_configurations(scratch)
        return {"modelConfigId": scratch["model"]["modelConfigId"],
                "inferenceConfigId": scratch["inference"]["inferenceConfigId"]}

    def create_configurations(self, resources):
        model = self.api.call("POST", self.root + "/model-configurations", {
            "catalogEntryId": self.c["catalogEntryId"],
            "resolvedCheckpointRef": self.c["checkpointRef"],
            "modelSettings": self.c.get("modelSettings", {}),
        }, expected=201)
        resources["model"] = model
        self.persist()
        inference = self.api.call("POST", self.root + "/inference-configurations", {
            "engineId": self.c["engineId"],
            "servingSettings": self.c.get("servingSettings", {}),
            "generationSettings": self.c.get("generationSettings", {}),
        }, expected=201)
        resources["inference"] = inference
        self.persist()

    def verify_configurations(self, resources):
        for kind, field in (("model", "modelConfigId"), ("inference", "inferenceConfigId")):
            expected = resources[kind]
            rows = self.api.call("GET", self.root + f"/{kind}-configurations")["items"]
            require(any(stable(row) == stable(expected) for row in rows),
                    f"Persisted {field} did not roundtrip exactly")

    def cleanup(self):
        return self.cleanup_configurations(self.e["resources"].get("scratch", {}))

    def cleanup_configurations(self, resources):
        deleted, errors = [], []
        for kind, field in (("inference", "inferenceConfigId"), ("model", "modelConfigId")):
            if kind not in resources:
                continue
            configuration_id = resources[kind][field]
            path = self.root + f"/{kind}-configurations"
            try:
                self.api.call("DELETE", path + "/" + quote(configuration_id, safe=""), expected=204)
                rows = self.api.call("GET", path)["items"]
                require(all(row[field] != configuration_id for row in rows),
                        f"Deleted {field} remains in configuration history")
                deleted.append(configuration_id)
                resources.setdefault("deletedIds", []).append(configuration_id)
                self.persist()
            except (AssertionError, KeyError, TypeError, ValueError, RuntimeError, OSError, URLError) as error:
                errors.append(f"{kind} {configuration_id}: {type(error).__name__}: {error}")
        require(not errors, "Owned configuration cleanup failed: " + "; ".join(errors))
        return {"deletedIds": deleted, "verifiedAbsent": True, "azureResourcesDeleted": False}

    def deploy(self):
        if self.c.get("allowDeploy") is not True:
            raise Blocked("allowDeploy=true required; deployment changes the selected environment")
        resources = self.e["resources"]
        try:
            self.create_configurations(resources)
            self.verify_configurations(resources)
            started = self.api.call("POST", self.root + "/deployments", {
                "modelConfigId": resources["model"]["modelConfigId"],
                "inferenceConfigId": resources["inference"]["inferenceConfigId"],
            }, expected=202)
            resources["deployment"] = started
        finally:
            if "deployment" not in resources:
                self.check("undeployed-configuration-cleanup",
                           lambda: self.cleanup_configurations(resources))
        self.persist()
        path = self.root + "/deployments/" + quote(started["deploymentRevisionId"], safe="")
        revision = self.poll(path, "lifecycleState", "ready", {"deployment_failed", "superseded"})
        self.verify_model(revision["configuration"])
        require(revision["health"]["status"] == "healthy", "Engine is not healthy")
        return revision

    def verify_model(self, configuration):
        for key in ("catalogEntryId", "resolvedCheckpointRef"):
            expected = self.c["checkpointRef" if key == "resolvedCheckpointRef" else key]
            require(configuration[key] == expected, f"Wrong deployed {key}")

    def inference(self):
        payload = self.api.call("POST", self.root + "/prompts", {
            "prompt": "Say hello.", "parameters": {"temperature": 0.0, "max_tokens": 8},
        })
        require(payload["responseText"].strip(), "Empty model response")
        revision = self.e["resources"]["deployment"]["deploymentRevisionId"]
        require(payload["deploymentRevisionId"] == revision, "Prompt used wrong revision")
        number(payload["timing"]["ttftMs"], "ttftMs", 0.001, 120_000)
        return payload

    def run(self, run_type, definition):
        started = self.api.call("POST", self.root + "/runs", {
            "runType": run_type, "testDefinitionRef": definition,
        }, expected=202)
        run_id = started["runId"]
        resource = {"runId": run_id, "runType": run_type, "testDefinitionRef": definition}
        self.e["resources"]["runs"].append(resource)
        self.persist()
        path = self.root + "/runs/" + quote(run_id, safe="")
        try:
            run = self.poll(path, "status", "completed",
                            {"failed", "incomplete", "cancelled"})
        except TimeoutError:
            resource["cancellation"] = self.api.call("POST", path + "/cancel")
            self.persist()
            raise
        report = self.api.call("GET", path + "/report")
        resource.update(run=run, report=report)
        self.persist()
        require(report["completenessIndicator"] == "complete", f"Incomplete report: {report}")
        require(report["runId"] == run_id, "Wrong report run")
        expected_revision = self.e["resources"]["deployment"]["deploymentRevisionId"]
        require(run["deploymentRevisionId"] == expected_revision, "Run used another revision")
        self.verify_model(report["configuration"])
        return report

    def golden(self):
        policy = self.c["golden"]
        rows = self.api.call("GET", "/golden-datasets")["goldenDatasets"]
        definition = find(rows, "goldenDatasetId", policy["id"])
        require(definition["reviewStatus"] == "reviewed", "Golden dataset is unreviewed")
        require(definition["version"] == policy["version"], "Wrong golden dataset version")
        require(definition["caseCount"] == policy["caseCount"], "Golden case count mismatch")
        number(policy["minPassRate"], "minPassRate", 0.001, 1)
        report = self.run("quality-golden", policy["id"])
        quality = report["quality"]
        aggregate = quality["aggregate"]
        cases = quality["cases"]
        require(len(cases) == policy["caseCount"], "Missing golden case outcomes")
        require(len({case["caseId"] for case in cases}) == len(cases),
                "Duplicate golden case outcomes")
        require(all(case["caseId"] and case["observedOutcome"].strip() for case in cases),
                "Golden cases missing IDs or observed model outcomes")
        for status in ("passed", "failed", "errored", "skipped", "incomplete"):
            require(aggregate[status] == sum(case["status"] == status for case in cases),
                    f"Golden {status} aggregate does not match actual case outcomes")
        require(aggregate["totalCases"] == policy["caseCount"], "Wrong golden total")
        require(all(aggregate[key] == 0 for key in ("errored", "skipped", "incomplete")),
                f"Golden errors/skips/incomplete: {aggregate}")
        require(aggregate["passRate"] >= policy["minPassRate"], f"Golden threshold: {aggregate}")
        require(sum(case["status"] == "passed" for case in cases) / len(cases)
                >= policy["minPassRate"], "Actual golden outcomes missed pass-rate threshold")
        return report

    def performance(self, mode):
        policy = self.c["performance"][mode]
        # These IDs reuse the repository's real LLMPerf runner and bounded seeded workloads.
        definitions = {
            "single": ("llmperf-single-stream-v1", 1, 25, 40),
            "concurrent": ("chatbot-concurrent-10-v1", 10, 50, 80),
        }
        definition, concurrency, requests, max_requests = definitions[mode]
        if self.c.get("seededWorkloadsVerified") is not True:
            raise Blocked("Operator must verify persisted seeded workload safety bounds first")
        rows = self.api.call("GET", "/performance-workloads")["performanceWorkloads"]
        row = find(rows, "workloadId", definition)
        require(row["version"] == 1 and row["concurrency"] == concurrency,
                "Unexpected workload version/concurrency")
        number(policy["maxP95LatencyMs"], "maxP95LatencyMs", 0.001, 600_000)
        number(policy["minTokensPerSecond"], "minTokensPerSecond", 0.001, 1_000_000)
        number(policy["maxFailureRate"], "maxFailureRate", 0, 0.1)
        report = self.run("performance", definition)
        perf = report["performance"]
        require(perf["runner"] == "llmperf", "Unexpected performance runner")
        conditions = perf["testConditions"]
        require(conditions["concurrency"] == concurrency, "Actual concurrency mismatch")
        require(conditions["durationOrRequestCount"] == {"requestCount": requests},
                "Actual request bound mismatch")
        require(conditions["safetyLimits"] == {
            "maxRequests": max_requests, "maxConcurrency": concurrency, "timeoutSeconds": 600,
        }, "Actual safety bounds mismatch")
        require(perf["units"]["endToEndLatencyMs"] == "ms", "Wrong latency units")
        require(perf["units"]["throughputTokensPerSec"] == "tokens/sec", "Wrong throughput units")
        metrics, failures = perf["metrics"], perf["requestFailures"]
        latency = number(metrics["endToEndLatencyMs"]["p95"], "p95", 0.001, 600_000)
        throughput = number(metrics["throughputTokensPerSec"], "throughput", 0.001, 1_000_000)
        number(failures["total"], "request total", requests, max_requests)
        number(failures["count"], "request failures", 0, failures["total"])
        rate = failures["count"] / failures["total"]
        require(abs(failures["rate"] - rate) < 0.0001, "Inconsistent failure rate")
        require(latency <= policy["maxP95LatencyMs"], "P95 latency threshold exceeded")
        require(throughput >= policy["minTokensPerSecond"], "Throughput threshold missed")
        require(rate <= policy["maxFailureRate"], "Request failure threshold exceeded")
        return report

    def persistence(self, resources):
        self.verify_configurations(resources)
        history = self.api.call("GET", self.root + "/runs")["runs"]
        require(resources["runs"], "No run/report evidence to verify")
        for resource in resources["runs"]:
            require("report" in resource, "Cannot verify a run without its completed report")
            require(any(row["runId"] == resource["runId"] for row in history),
                    "Run absent from persisted history")
            path = self.root + "/runs/" + quote(resource["runId"], safe="")
            run = self.api.call("GET", path)
            require(stable(run) == stable(resource["run"]), "Persisted run changed")
            report = self.api.call("GET", path + "/report")
            require(stable(report) == stable(resource["report"]), "Persisted report changed")
        return {"runCount": len(resources["runs"]), "freshHttpReads": True}


def execute(config, api, evidence, persist, stage, prior=None):
    harness = Acceptance(config, api, evidence, persist)
    if not harness.check("health-auth-readiness", harness.health):
        harness.check("remaining-stage", lambda: (_ for _ in ()).throw(
            Blocked("Health/auth prerequisite failed; no mutations attempted")))
        return
    if not harness.check("azure-environment-model", harness.environment):
        return
    if stage == "verify-persistence":
        def verify():
            if not prior:
                raise Blocked("--prior evidence required after an independently performed restart")
            require(prior["config"] == config, "Prior evidence targets another configuration")
            return harness.persistence(prior["resources"])
        harness.check("persisted-runs-reports-configurations", verify)
        return
    if stage == "gpu" and not harness.check("gpu-policy-inputs", lambda: validate_gpu(config)):
        return
    try:
        configs_ok = harness.check("configuration-db-roundtrip", harness.configurations)
    finally:
        cleanup_ok = harness.check("configuration-cleanup", harness.cleanup)
    if stage == "control":
        return
    if not configs_ok or not cleanup_ok or not harness.check("model-deploy-ready", harness.deploy):
        harness.check("gpu-checks", lambda: (_ for _ in ()).throw(
            Blocked("Deployment prerequisite unavailable; CPU evidence remains independent")))
        return
    harness.check("real-inference", harness.inference)
    harness.check("golden-evaluation", harness.golden)
    harness.check("single-stream-performance", lambda: harness.performance("single"))
    harness.check("concurrent-performance", lambda: harness.performance("concurrent"))
    harness.check("run-report-persistence", lambda: harness.persistence(evidence["resources"]))
    harness.check("application-restart", lambda: (_ for _ in ()).throw(
        Blocked("No restart API. Operator must restart independently, then verify-persistence; "
                "a fresh HTTP client alone is not restart evidence")))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--stage", choices=("control", "gpu", "verify-persistence"),
                        default="control")
    parser.add_argument("--prior", type=Path)
    args = parser.parse_args(argv)
    token = os.environ.get("LIVE_OPERATOR_TOKEN", "")
    evidence = {
        "schemaVersion": 1, "scope": "real-main-cloud-api", "stage": args.stage,
        "startedAt": datetime.now(timezone.utc).isoformat(), "checks": [],
        "exchanges": [], "resources": {"runs": []}, "fullAcceptance": False,
        "sourceCommit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=Path(__file__).parent, text=True,
        ).strip(),
        "harnessSha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "sourceProvenance": "deployedSourceCommit/deploymentEvidence are operator-supplied, "
                            "not independently exposed by the current health API",
    }

    def persist():
        args.evidence.parent.mkdir(parents=True, exist_ok=True)
        text = json.dumps(evidence, indent=2, allow_nan=False)
        if token:
            text = text.replace(token, "[REDACTED]")
        # Owner-only evidence can contain prompts, diagnostic details and environment metadata.
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", dir=args.evidence.parent, prefix=".acceptance-", delete=False,
            ) as stream:
                temporary = Path(stream.name)
                stream.write(text + "\n")
            os.replace(temporary, args.evidence)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    try:
        config = load_config(args.config)
        evidence["config"] = config
        if not token or token != token.strip() or "\n" in token or "\r" in token:
            raise Blocked("LIVE_OPERATOR_TOKEN must contain an authorized actual operator token")
        prior = read_json(args.prior) if args.prior else None
        api = API(config, token, evidence["exchanges"])
        execute(config, api, evidence, persist, args.stage, prior)
    except (Blocked, TypeError, ValueError, KeyError, OSError, subprocess.SubprocessError) as error:
        evidence["checks"].append({
            "name": "live-inputs", "status": "blocked", "error": f"{type(error).__name__}: {error}",
        })
    statuses = [check["status"] for check in evidence["checks"]]
    evidence["status"] = "failed" if "failed" in statuses else (
        "blocked" if "blocked" in statuses else "passed"
    )
    evidence["endedAt"] = datetime.now(timezone.utc).isoformat()
    persist()
    print(json.dumps({"status": evidence["status"], "fullAcceptance": False,
                      "checks": [{"name": check["name"], "status": check["status"]}
                                 for check in evidence["checks"]]}))
    return {"passed": 0, "failed": 1, "blocked": 2}[evidence["status"]]


if __name__ == "__main__":
    raise SystemExit(main())
