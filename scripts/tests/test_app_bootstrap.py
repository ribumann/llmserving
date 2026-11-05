import copy
import hashlib
import http.server
import importlib.util
import json
import os
from pathlib import Path
import select
import shutil
import socket
import socketserver
import ssl
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch
import zipfile


SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location("app_bootstrap", SCRIPTS / "app_bootstrap.py")
bootstrap = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bootstrap)

class TunnelProxyHandler(socketserver.BaseRequestHandler):
    def handle(self):
        stream = self.request.makefile("rb")
        request_line = stream.readline().decode("ascii").rstrip("\r\n")
        headers = []
        while True:
            line = stream.readline()
            if line in {b"", b"\r\n", b"\n"}:
                break
            headers.append(line.decode("ascii").rstrip("\r\n"))
        stream.close()
        self.server.tunnel_requests.append((request_line, headers))
        if not request_line.startswith("CONNECT synthetic-vault.vault.azure.net:443 HTTP/1.") or any(
            header.lower().startswith("proxy-authorization:") for header in headers
        ):
            self.request.sendall(b"HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\n\r\n")
            return
        with socket.create_connection(("127.0.0.1", self.server.target_port)) as upstream:
            self.request.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
            while True:
                readable, _, _ = select.select([self.request, upstream], [], [], 5)
                if not readable:
                    return
                for source in readable:
                    data = source.recv(65536)
                    if not data:
                        return
                    destination = upstream if source is self.request else self.request
                    destination.sendall(data)


class ThreadedTunnelProxy(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


class ThreadedHttpServer(http.server.ThreadingHTTPServer):
    daemon_threads = True


class BootstrapTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        proxy_env = patch.dict(os.environ, {
            "HTTPS_PROXY": "http://127.0.0.1:3128",
            "https_proxy": "http://127.0.0.1:3128",
        })
        proxy_env.start()
        self.addCleanup(proxy_env.stop)
        package = self.root / "functions.zip"
        with zipfile.ZipFile(package, "w") as archive:
            archive.writestr("host.json", "{}")
            archive.writestr("function_app.py", "# synthetic fixture")
        self.inputs = self.root / "inputs.json"
        self.contract = {
            "acr_login_server": "synthetic.azurecr.io",
            "vault_name": "synthetic-vault",
            "images": {
                name: f"synthetic.azurecr.io/{name.replace('_', '-')}@sha256:{'a' * 64}"
                for name in bootstrap.IMAGES
            },
            "functions_zip": "functions.zip",
            "functions_sha256": hashlib.sha256(package.read_bytes()).hexdigest(),
            "allowed_email_domains": ["liberatetheinnerchild.net"],
            "operator_upn": "synthetic@liberatetheinnerchild.net",
        }

    def load(self):
        self.inputs.write_text(json.dumps(self.contract))
        return bootstrap.load_contract(self.inputs)

    def responses(self):
        return [
            {"id": bootstrap.SUBSCRIPTION, "tenantId": bootstrap.TENANT},
            {"id": bootstrap.ENVIRONMENT, "properties": {
                "provisioningState": "Succeeded",
                "defaultDomain": "synthetic.italynorth.azurecontainerapps.io",
            }},
            {"id": bootstrap.SHARED + "/providers/Microsoft.ContainerRegistry/registries/synthetic",
             "properties": {"loginServer": "synthetic.azurecr.io"}},
            {"id": bootstrap.SHARED + "/providers/Microsoft.KeyVault/vaults/synthetic-vault",
             "properties": {
                 "tenantId": bootstrap.TENANT,
                 "publicNetworkAccess": "Disabled", "enableRbacAuthorization": True,
                 "vaultUri": "https://synthetic-vault.vault.azure.net/",
             }},
            {"appId": bootstrap.CLIENT, "signInAudience": "AzureADMyOrg", "passwordCredentials": [],
             "web": {"redirectUris": [], "implicitGrantSettings": {
                 "enableIdTokenIssuance": False, "enableAccessTokenIssuance": False,
             }}},
        ]

    def test_validate_is_offline_and_emits_exact_inputs(self):
        with patch.object(bootstrap, "az_json") as azure:
            contract = self.load()
            values = bootstrap.control_inputs(contract)
        azure.assert_not_called()
        self.assertEqual(len([key for key in values if key.endswith("_image")]), 7)
        self.assertTrue(values["enable_sso"])
        self.assertEqual(values["auth_allowed_email_domains"], "liberatetheinnerchild.net")
        self.assertEqual(values["existing_sso_client_id"], bootstrap.CLIENT)
        self.assertEqual(values["functions_package_sha256"], contract["functions_sha256"])
        self.assertTrue(values["manage_database_url_secret"])
        self.assertEqual(values["existing_sso_secret_id"],
                         "https://synthetic-vault.vault.azure.net/secrets/sso-client-secret")

    def test_rejects_bad_artifact_and_policy_inputs(self):
        original = copy.deepcopy(self.contract)
        for field, value in [
            ("allowed_email_domains", ["example.com"]),
            ("allowed_email_domains", ["*.liberatetheinnerchild.net"]),
            ("allowed_email_domains", ["evilliberatetheinnerchild.net"]),
            ("allowed_email_domains", []),
            ("allowed_email_domains", [True]),
            ("allowed_email_domains", ["foreign.example"]),
            ("operator_upn", "synthetic@foreign.example"),
            ("functions_sha256", "0" * 64),
            ("functions_zip", "missing.zip"),
            ("images", {"backend": "synthetic.azurecr.io/backend:latest"}),
            ("vault_name", "https://foreign.example"),
        ]:
            with self.subTest(field=field, value=value):
                self.contract = {**original, field: value}
                with self.assertRaises((ValueError, OSError)):
                    self.load()
        for reference in ["synthetic.azurecr.io/backend:latest",
                          f"foreign.azurecr.io/backend@sha256:{'a' * 64}"]:
            self.contract = copy.deepcopy(original)
            self.contract["images"]["backend"] = reference
            with self.assertRaises(ValueError):
                self.load()

    def test_zip_content_and_symlink_are_rejected(self):
        package = self.root / "functions.zip"
        package.write_bytes(b"not a zip")
        self.contract["functions_sha256"] = hashlib.sha256(package.read_bytes()).hexdigest()
        with self.assertRaises(bootstrap.BootstrapError):
            self.load()
        with zipfile.ZipFile(package, "w") as archive:
            archive.writestr("nested/host.json", "{}")
        self.contract["functions_sha256"] = hashlib.sha256(package.read_bytes()).hexdigest()
        with self.assertRaises(bootstrap.BootstrapError):
            self.load()
        alias = self.root / "alias.zip"
        alias.symlink_to(package)
        self.contract["functions_zip"] = str(alias)
        with self.assertRaises(ValueError):
            self.load()

    def test_preview_only_reads_and_uses_actual_environment_domain(self):
        contract = self.load()
        with patch.object(bootstrap, "az_json", side_effect=self.responses()) as azure:
            plan = bootstrap.preview(contract)
        self.assertEqual(plan["callbacks"], [
            f"https://llmrelease-{name}.synthetic.italynorth.azurecontainerapps.io/.auth/login/aad/callback"
            for name in ("frontend", "backend")
        ])
        for call in azure.call_args_list[1:]:
            self.assertEqual(call.args[:3], ("rest", "--method", "GET"))
        digest = bootstrap.approval_hash(plan)
        changed = copy.deepcopy(plan)
        changed["current_id_token_issuance"] = True
        self.assertNotEqual(digest, bootstrap.approval_hash(changed))

    def test_preview_blocks_wrong_scope_or_reused_application(self):
        mutations = [
            (0, "tenantId", "foreign"),
            (1, "id", bootstrap.ENVIRONMENT.replace("llmrelease", "production")),
            (1, "properties", {"provisioningState": "Creating"}),
            (2, "properties", {"loginServer": "foreign.azurecr.io"}),
            (3, "properties", {**self.responses()[3]["properties"], "publicNetworkAccess": "Enabled"}),
            (4, "signInAudience", "AzureADMultipleOrgs"),
            (4, "web", {"redirectUris": ["https://production.example/callback"]}),
        ]
        contract = self.load()
        for index, key, value in mutations:
            with self.subTest(index=index, key=key):
                responses = self.responses()
                responses[index][key] = value
                with patch.object(bootstrap, "az_json", side_effect=responses):
                    with self.assertRaises(bootstrap.BootstrapError):
                        bootstrap.preview(contract)

    def test_initial_secret_preview_does_not_need_environment(self):
        responses = self.responses()
        del responses[1]
        with patch.object(bootstrap, "az_json", side_effect=responses) as azure:
            plan = bootstrap.preview(self.load(), callbacks=False)
        self.assertEqual(plan["phase"], "initial-secret")
        self.assertEqual(plan["callbacks"], [])
        self.assertIsNone(plan["environment_id"])
        self.assertFalse(any("managedEnvironments" in str(call) for call in azure.call_args_list))

    def test_actual_operator_domain_is_explicit_and_accepted(self):
        self.contract["allowed_email_domains"] = ["mngenvmcap621318.onmicrosoft.com"]
        self.contract["operator_upn"] = "admin@MngEnvMCAP621318.onmicrosoft.com"
        self.assertEqual(bootstrap.control_inputs(self.load())["auth_allowed_email_domains"],
                         "mngenvmcap621318.onmicrosoft.com")

    def test_callback_patch_is_exact_and_preserves_access_token_setting(self):
        plan = {"callbacks": ["https://synthetic/callback"],
                "current_access_token_issuance": False}
        with patch.object(bootstrap, "azure_token", return_value="not-real") as token, \
             patch.object(bootstrap, "request_json") as request:
            bootstrap.mutate("set-callbacks", self.load(), plan, None)
        token.assert_called_once_with("https://graph.microsoft.com")
        self.assertEqual(request.call_args.args[:3],
                         ("graph.microsoft.com", bootstrap.APP_PATH, "PATCH"))
        self.assertEqual(request.call_args.args[4], {"web": {
            "redirectUris": plan["callbacks"],
            "implicitGrantSettings": {"enableIdTokenIssuance": True,
                                     "enableAccessTokenIssuance": False},
        }})

    def test_secret_only_moves_from_fd_to_exact_https_payload(self):
        read_fd, write_fd = os.pipe()
        self.addCleanup(os.close, read_fd)
        os.write(write_fd, b"synthetic-credential\n")
        os.close(write_fd)
        with patch.object(bootstrap, "azure_token", return_value="not-real") as token, \
             patch.object(bootstrap, "request_json") as request:
            bootstrap.mutate("store-secret", self.load(), {}, read_fd)
        token.assert_called_once_with("https://vault.azure.net")
        self.assertEqual(request.call_args.args[:3], (
            "synthetic-vault.vault.azure.net", "/secrets/sso-client-secret?api-version=7.4", "PUT",
        ))
        self.assertEqual(request.call_args.args[4]["value"], "synthetic-credential")
        with self.assertRaises(bootstrap.BootstrapError):
            bootstrap.mutate("store-secret", self.load(), {}, None)

    def test_create_secret_moves_graph_response_directly_to_private_vault(self):
        key = "11111111-2222-3333-4444-555555555555"
        plan = {"existing_credential_key_ids": [], "new_credential": {
            "displayName": "main-container-apps-easy-auth", "endDateTime": "2027-01-01T00:00:00Z",
        }}
        credential = {"keyId": key, "secretText": "synthetic-generated-secret"}
        events = []
        def token(resource):
            events.append(("token", resource))
            return "synthetic-token"
        def request(*args, **kwargs):
            events.append(("request", args, kwargs))
            return credential if args[0] == "graph.microsoft.com" else None
        with patch.object(bootstrap, "azure_token", side_effect=token), \
             patch.object(bootstrap, "request_json", side_effect=request), \
             patch.object(bootstrap, "check_vault_connectivity") as preflight, \
             patch.object(bootstrap.subprocess, "run") as process:
            bootstrap.mutate("create-secret", self.load(), plan, None)
        process.assert_not_called()
        preflight.assert_called_once_with("synthetic-vault.vault.azure.net")
        self.assertEqual([event[0] for event in events], ["token", "token", "request", "request"])
        self.assertEqual(events[2][1][:3], (
            "graph.microsoft.com", bootstrap.APP_PATH + "/addPassword", "POST",
        ))
        self.assertEqual(events[2][1][4], {"passwordCredential": plan["new_credential"]})
        self.assertEqual(events[2][2], {"read_response": True})
        self.assertEqual(events[3][1][:3], (
            "synthetic-vault.vault.azure.net", "/secrets/sso-client-secret?api-version=7.4", "PUT",
        ))
        self.assertEqual(events[3][1][4]["value"], credential["secretText"])

    def test_create_secret_partial_failure_names_only_recovery_key(self):
        key = "11111111-2222-3333-4444-555555555555"
        plan = {"existing_credential_key_ids": [], "new_credential": {}}
        with patch.object(bootstrap, "azure_token", return_value="synthetic-token"), \
             patch.object(bootstrap, "request_json", side_effect=[
                 {"keyId": key, "secretText": "synthetic-generated-secret"},
                 bootstrap.BootstrapError("private vault unavailable"),
             ]), patch.object(bootstrap, "check_vault_connectivity"):
            with self.assertRaises(bootstrap.BootstrapError) as error:
                bootstrap.mutate("create-secret", self.load(), plan, None)
        self.assertIn(key, str(error.exception))
        self.assertNotIn("synthetic-generated-secret", str(error.exception))
        self.assertIn("Do not retry", str(error.exception))

    def test_create_secret_rejects_existing_credentials_before_token_or_mutation(self):
        with patch.object(bootstrap, "azure_token") as token, \
             patch.object(bootstrap, "request_json") as request:
            with self.assertRaises(bootstrap.BootstrapError):
                bootstrap.mutate("create-secret", self.load(), {
                    "existing_credential_key_ids": ["11111111-2222-3333-4444-555555555555"],
                }, None)
        token.assert_not_called()
        request.assert_not_called()

    def test_create_secret_requires_vault_connect_before_creating_credential(self):
        with patch.object(
            bootstrap, "check_vault_connectivity",
            side_effect=bootstrap.BootstrapError("private vault unavailable"),
        ), patch.object(bootstrap, "azure_token") as token, \
             patch.object(bootstrap, "request_json") as request:
            with self.assertRaises(bootstrap.BootstrapError):
                bootstrap.mutate("create-secret", self.load(), {
                    "existing_credential_key_ids": [],
                    "new_credential": {"displayName": "main"},
                }, None)
        token.assert_not_called()
        request.assert_not_called()

    def test_http_success_reads_sensitive_json_only_when_requested(self):
        connection = Mock()
        connection.getresponse.return_value.status = 200
        connection.getresponse.return_value.read.return_value = b'{"secretText":"synthetic"}'
        with patch.object(bootstrap.http.client, "HTTPSConnection", return_value=connection):
            result = bootstrap.request_json("graph.microsoft.com", bootstrap.APP_PATH + "/addPassword",
                                            "POST", "synthetic-token", {}, read_response=True)
        self.assertEqual(result["secretText"], "synthetic")
        connection.getresponse.return_value.read.assert_called_once_with(65537)

    def test_graph_request_is_direct_even_with_vault_proxy_configured(self):
        connection = Mock()
        connection.getresponse.return_value.status = 204
        with patch.object(bootstrap.http.client, "HTTPSConnection", return_value=connection) as create:
            bootstrap.request_json(bootstrap.GRAPH_HOST, bootstrap.APP_PATH, "PATCH",
                                   "synthetic-token", {})
        create.assert_called_once()
        self.assertEqual(create.call_args.args[0], bootstrap.GRAPH_HOST)
        connection.set_tunnel.assert_not_called()

    def test_vault_proxy_rejects_non_loopback_and_embedded_credentials(self):
        for endpoint in ("http://proxy.example:3128", "http://user:pass@127.0.0.1:3128",
                         "https://127.0.0.1:3128", "http://127.0.0.1/path",
                         "http://localhost:3128", "http://127.0.0.1:65536",
                         "http://127.0.0.1:3128?ignored"):
            with self.subTest(endpoint=endpoint), patch.dict(os.environ, {
                "HTTPS_PROXY": endpoint, "https_proxy": endpoint,
            }):
                with self.assertRaises(bootstrap.BootstrapError):
                    bootstrap.loopback_vault_proxy()

    def test_conflicting_proxy_settings_fail_without_a_direct_fallback(self):
        with patch.dict(os.environ, {
            "HTTPS_PROXY": "http://127.0.0.1:3128",
            "https_proxy": "http://127.0.0.1:3129",
        }), patch.object(bootstrap.http.client, "HTTPSConnection") as create:
            with self.assertRaises(bootstrap.BootstrapError):
                bootstrap.https_connection("synthetic-vault.vault.azure.net")
        create.assert_not_called()

    def test_unset_proxy_preserves_direct_private_network_transport(self):
        with patch.dict(os.environ, {"HTTPS_PROXY": "", "https_proxy": ""}), patch.object(
            bootstrap.http.client, "HTTPSConnection",
        ) as create:
            bootstrap.https_connection("synthetic-vault.vault.azure.net")
        self.assertEqual(create.call_args.args, ("synthetic-vault.vault.azure.net",))
        create.return_value.set_tunnel.assert_not_called()

    def test_vault_request_uses_real_loopback_connect_and_verified_tls(self):
        openssl = shutil.which("openssl")
        if openssl is None:
            self.skipTest("OpenSSL is required to generate the temporary TLS fixture.")
        certificate = self.root / "certificate.pem"
        private_key = self.root / "private-key.pem"
        subprocess.run([
            openssl, "req", "-x509", "-newkey", "rsa:2048", "-nodes",
            "-keyout", str(private_key), "-out", str(certificate),
            "-days", "1", "-subj", "/CN=synthetic-vault.vault.azure.net",
            "-addext", "subjectAltName=DNS:synthetic-vault.vault.azure.net",
        ], check=True, capture_output=True, timeout=30)
        received = []

        class VaultHandler(http.server.BaseHTTPRequestHandler):
            def do_PUT(self):
                received.append((
                    self.path,
                    self.headers.get("Authorization"),
                    self.rfile.read(int(self.headers["Content-Length"])),
                ))
                self.send_response(204)
                self.end_headers()

            def log_message(self, *_args):
                pass

        tls_server = ThreadedHttpServer(("127.0.0.1", 0), VaultHandler)
        server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        server_context.load_cert_chain(certificate, private_key)
        tls_server.socket = server_context.wrap_socket(tls_server.socket, server_side=True)
        server_thread = threading.Thread(target=tls_server.serve_forever, daemon=True)
        server_thread.start()
        proxy = ThreadedTunnelProxy(("127.0.0.1", 0), TunnelProxyHandler)
        proxy.target_port = tls_server.server_address[1]
        proxy.tunnel_requests = []
        proxy_thread = threading.Thread(target=proxy.serve_forever, daemon=True)
        proxy_thread.start()
        self.addCleanup(proxy.server_close)
        self.addCleanup(proxy.shutdown)
        self.addCleanup(tls_server.server_close)
        self.addCleanup(tls_server.shutdown)
        proxy_url = f"http://127.0.0.1:{proxy.server_address[1]}"
        real_create_default_context = ssl.create_default_context
        with patch.dict(os.environ, {"HTTPS_PROXY": proxy_url, "https_proxy": proxy_url}):
            with patch.object(
                bootstrap.ssl, "create_default_context",
                side_effect=lambda: real_create_default_context(cafile=str(certificate)),
            ):
                bootstrap.request_json(
                    "synthetic-vault.vault.azure.net", "/secrets/name?api-version=7.4",
                    "PUT", "synthetic-token", {"value": "synthetic-secret"},
                )
            # The same tunnel must reject an untrusted certificate before sending credentials.
            with self.assertRaises(bootstrap.BootstrapError):
                bootstrap.request_json(
                    "synthetic-vault.vault.azure.net", "/secrets/name?api-version=7.4",
                    "PUT", "synthetic-token", {"value": "synthetic-secret"},
                )
        self.assertEqual(len(proxy.tunnel_requests), 2)
        self.assertTrue(proxy.tunnel_requests[0][0].startswith(
            "CONNECT synthetic-vault.vault.azure.net:443 HTTP/1."
        ))
        self.assertFalse(any(
            header.lower().startswith("proxy-authorization:")
            for header in proxy.tunnel_requests[0][1]
        ))
        self.assertEqual(received, [(
            "/secrets/name?api-version=7.4", "Bearer synthetic-token",
            b'{"value": "synthetic-secret"}',
        )])

    def test_http_failure_never_reads_or_prints_secret_response(self):
        connection = Mock()
        connection.getresponse.return_value.status = 403
        with patch.object(bootstrap.http.client, "HTTPSConnection", return_value=connection):
            with self.assertRaisesRegex(bootstrap.BootstrapError, "HTTP 403"):
                bootstrap.request_json("synthetic-vault.vault.azure.net", "/secrets/name", "PUT",
                                       "synthetic-token", {"value": "synthetic-secret"})
        connection.getresponse.return_value.read.assert_not_called()
        connection.close.assert_called_once()

    def test_redirect_is_rejected_without_forwarding_credentials(self):
        connection = Mock()
        connection.getresponse.return_value.status = 307
        with patch.object(bootstrap.http.client, "HTTPSConnection", return_value=connection) as create:
            with self.assertRaisesRegex(bootstrap.BootstrapError, "HTTP 307"):
                bootstrap.request_json("synthetic-vault.vault.azure.net", "/secrets/name", "PUT",
                                       "synthetic-token", {"value": "synthetic-secret"})
        self.assertEqual(create.call_count, 1)
        self.assertEqual(connection.request.call_count, 1)
        connection.getresponse.return_value.read.assert_not_called()

    def test_cli_failure_suppresses_diagnostics_and_binds_subscription(self):
        result = subprocess.CompletedProcess([], 1, b"", b"SENSITIVE diagnostic")
        with patch.object(bootstrap.subprocess, "run", return_value=result) as run:
            with self.assertRaises(bootstrap.BootstrapError) as error:
                bootstrap.az_json("account", "show")
        self.assertNotIn("SENSITIVE", str(error.exception))
        self.assertIn(bootstrap.SUBSCRIPTION, run.call_args.args[0])

    def test_windows_azure_cli_resolution_uses_path_and_suppresses_diagnostics(self):
        with patch.object(bootstrap.os, "name", "nt"), patch.object(
            bootstrap.shutil, "which", return_value=r"C:\Azure CLI\az.cmd"
        ), patch.object(
            bootstrap.subprocess, "run",
            return_value=subprocess.CompletedProcess([], 0, '{"id":"expected"}', ""),
        ) as run:
            self.assertEqual(bootstrap.az_json("account", "show"), {"id": "expected"})
            self.assertEqual(run.call_args.args[0][0], r"C:\Azure CLI\az.cmd")
            self.assertNotIn("shell", run.call_args.kwargs)
            self.assertFalse(any(
                name.lower() in {"http_proxy", "https_proxy", "all_proxy"}
                for name in run.call_args.kwargs["env"]
            ))
        with patch.object(bootstrap.os, "name", "nt"), patch.object(
            bootstrap.shutil, "which", return_value=None
        ), patch.object(bootstrap.subprocess, "run") as run:
            with self.assertRaises(bootstrap.BootstrapError):
                bootstrap.az_json("account", "show")
            run.assert_not_called()

    def test_https_request_carries_bearer_token_and_exact_body(self):
        connection = Mock()
        connection.getresponse.return_value.status = 204
        with patch.object(bootstrap.http.client, "HTTPSConnection", return_value=connection):
            bootstrap.request_json("graph.microsoft.com", bootstrap.APP_PATH, "PATCH",
                                   "synthetic-token", {"web": {"redirectUris": []}})
        request = connection.request.call_args
        self.assertEqual(request.args, ("PATCH", bootstrap.APP_PATH))
        self.assertEqual(request.kwargs["headers"]["Authorization"],
                         " ".join(("Bearer", "synthetic-token")))
        self.assertEqual(json.loads(request.kwargs["body"]), {"web": {"redirectUris": []}})
        connection.getresponse.return_value.read.assert_not_called()

    def test_missing_or_stale_approval_does_not_mutate(self):
        self.load()
        for approval in ([], ["--approve-preview-sha256", "0" * 64]):
            with patch.object(sys, "argv", [
                "app_bootstrap.py", "set-callbacks", "--inputs", str(self.inputs), *approval,
            ]), patch.object(bootstrap, "preview", return_value={"synthetic": True}), \
                 patch.object(bootstrap, "mutate") as mutate:
                with self.assertRaisesRegex(SystemExit, "approval"):
                    bootstrap.main()
                mutate.assert_not_called()


if __name__ == "__main__":
    unittest.main()
