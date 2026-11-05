"""Exercise the actual Squid ACL and TLS tunnel using a synthetic TLS server."""

import argparse
import http.client
import json
import os
import socket
import ssl
import subprocess
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import TestCase

HOST = "llmreleasestate0ea5e6.blob.core.windows.net"
VAULT = "llmrelease-kv-0ea5e6.vault.azure.net"
FUNCTIONS = "llmreleasefunc6ce138.blob.core.windows.net"


def request(authority: str, method: str = "CONNECT") -> int:
    with socket.create_connection(("127.0.0.1", 3128), timeout=3) as sock:
        sock.sendall(
            f"{method} {authority} HTTP/1.1\r\nHost: {authority}\r\n\r\n".encode()
        )
        response = http.client.HTTPResponse(sock)
        response.begin()
        return response.status


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--network-only", action="store_true")
    args = parser.parse_args()
    checks = TestCase()
    configuration = Path("/etc/llmserving/squid.conf").read_text()
    checks.assertIn("dns_nameservers 10.20.31.4", configuration)
    checks.assertNotIn("ssl_bump", configuration)
    checks.assertNotIn("cert=", configuration)
    checks.assertEqual(
        Path("/etc/llmserving/hosts.txt").read_text().splitlines(),
        [HOST, VAULT, FUNCTIONS],
    )
    subprocess.run(
        ["squid", "-k", "parse", "-f", "/etc/llmserving/squid.conf"], check=True
    )
    with tempfile.TemporaryDirectory() as temporary:
        directory = Path(temporary)
        directory.chmod(0o755)
        cert, key = directory / "cert.pem", directory / "key.pem"
        subprocess.run(
            [
                "openssl",
                "req",
                "-x509",
                "-newkey",
                "rsa:2048",
                "-nodes",
                "-keyout",
                str(key),
                "-out",
                str(cert),
                "-days",
                "1",
                "-subj",
                f"/CN={HOST}",
                "-addext",
                f"subjectAltName=DNS:{HOST},DNS:{VAULT},DNS:{FUNCTIONS}",
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        # CI supplies fixture-only container hosts entries, never production DNS.
        checks.assertEqual(socket.gethostbyname(HOST), "127.0.0.1")
        checks.assertEqual(socket.gethostbyname(VAULT), "127.0.0.1")
        checks.assertEqual(socket.gethostbyname(FUNCTIONS), "127.0.0.1")
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(cert, key)
        seen: set[str] = set()

        class Fixture(BaseHTTPRequestHandler):
            def log_message(self, *_: object) -> None:
                pass

            def do_HEAD(self) -> None:
                checks.assertEqual(self.headers["Host"], HOST)
                seen.add("backend")
                self.send_response(200)
                self.send_header("Content-Length", "0")
                self.send_header("x-ms-blob-type", "BlockBlob")
                self.end_headers()

            def do_GET(self) -> None:
                host = self.headers["Host"]
                if host == VAULT and self.path.startswith("/secrets/fixture"):
                    seen.add("vault")
                    body = json.dumps(
                        {
                            "value": "synthetic-not-a-secret",
                            "id": f"https://{VAULT}/secrets/fixture/version",
                        }
                    ).encode()
                    status, content_type = 200, "application/json"
                elif host == HOST and "comp=list" in self.path:
                    seen.add("backend")
                    body = (
                        f'<EnumerationResults ServiceEndpoint="https://{HOST}/" '
                        'ContainerName="tfstate"><Blobs/><NextMarker/></EnumerationResults>'
                    ).encode()
                    status, content_type = 200, "application/xml"
                elif host == HOST and self.path.startswith("/tfstate/"):
                    seen.add("backend")
                    body = json.dumps(
                        {
                            "version": 4,
                            "terraform_version": "1.16.6",
                            "serial": 1,
                            "lineage": "00000000-0000-0000-0000-000000000001",
                            "outputs": {},
                            "resources": [],
                        }
                    ).encode()
                    status, content_type = 200, "application/json"
                elif host in {HOST, FUNCTIONS} and self.path == "/tls-fixture":
                    body = b"tls-end-to-end"
                    status, content_type = 200, "text/plain"
                else:
                    body = b"Unexpected fixture request"
                    status, content_type = 400, "text/plain"
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("x-ms-request-id", "synthetic-fixture")
                if status == 404:
                    self.send_header("x-ms-error-code", "BlobNotFound")
                self.end_headers()
                self.wfile.write(body)

        with ThreadingHTTPServer(("127.0.0.1", 443), Fixture) as server:
            server.socket = context.wrap_socket(server.socket, server_side=True)
            thread = threading.Thread(target=server.serve_forever)
            thread.start()
            proxy = subprocess.Popen(
                ["squid", "-N", "-f", "/etc/llmserving/squid.conf"],
                stdout=subprocess.DEVNULL,
            )
            try:
                for attempt in range(50):
                    if proxy.poll() is not None:
                        raise RuntimeError("Squid stopped during startup")
                    try:
                        with socket.create_connection(("127.0.0.1", 3128), timeout=0.1):
                            break
                    except OSError:
                        if attempt == 49:
                            raise
                        time.sleep(0.1)
                for authority, method in (
                    ("example.com:443", "CONNECT"),
                    (f"{HOST}.evil.example:443", "CONNECT"),
                    (f"sub.{HOST}:443", "CONNECT"),
                    (f"{FUNCTIONS}.evil.example:443", "CONNECT"),
                    (f"sub.{FUNCTIONS}:443", "CONNECT"),
                    ("llmreleasefunc6ce139.blob.core.windows.net:443", "CONNECT"),
                    ("127.0.0.1:443", "CONNECT"),
                    (f"{HOST}:80", "CONNECT"),
                    (f"http://{HOST}/", "GET"),
                ):
                    checks.assertEqual(
                        request(authority, method), 403, (authority, method)
                    )
                client = ssl.create_default_context(cafile=str(cert))
                for host in (HOST, FUNCTIONS):
                    with socket.create_connection(("127.0.0.1", 3128), timeout=3) as sock:
                        sock.sendall(
                            f"CONNECT {host}:443 HTTP/1.1\r\nHost: {host}:443\r\n\r\n".encode()
                        )
                        header = bytearray()
                        while not header.endswith(b"\r\n\r\n"):
                            chunk = sock.recv(1)
                            if not chunk:
                                raise RuntimeError("Proxy closed before CONNECT response")
                            header.extend(chunk)
                        checks.assertIn(b" 200 ", header.split(b"\r\n")[0])
                        with client.wrap_socket(sock, server_hostname=host) as tls:
                            checks.assertEqual(
                                ssl.PEM_cert_to_DER_cert(cert.read_text()),
                                tls.getpeercert(binary_form=True),
                            )
                            tls.sendall(
                                f"GET /tls-fixture HTTP/1.1\r\nHost: {host}\r\n\r\n".encode()
                            )
                            response = http.client.HTTPResponse(tls)
                            response.begin()
                            checks.assertEqual(response.read(), b"tls-end-to-end")
                if args.network_only:
                    print("Network-only Squid ACL and unchanged TLS peer passed")
                    return
                environment = {
                    **os.environ,
                    "HTTPS_PROXY": "http://127.0.0.1:3128",
                    "https_proxy": "http://127.0.0.1:3128",
                    "NO_PROXY": "",
                    "no_proxy": "",
                    "SSL_CERT_FILE": str(cert),
                    "REQUESTS_CA_BUNDLE": str(cert),
                }
                subprocess.run(
                    ["/opt/vault-client"],
                    env=environment,
                    check=True,
                    timeout=20,
                )
                # Requests is the packaged Azure CLI Python transport dependency.
                subprocess.run(
                    [
                        "python",
                        "-c",
                        f"import requests; r=requests.get('https://{VAULT}/secrets/fixture', timeout=5); r.raise_for_status(); assert r.json()['value']=='synthetic-not-a-secret'",
                    ],
                    env=environment,
                    check=True,
                    timeout=15,
                )
                native = directory / "backend"
                native.mkdir()
                (native / "main.tf").write_text(
                    'terraform {\nbackend "azurerm" {\n'
                    f'storage_account_name = "{HOST.split(".")[0]}"\n'
                    'container_name = "tfstate"\nkey = "fixture.tfstate"\n'
                    'sas_token = "sv=2023-11-03&sig=synthetic-fixture"\n'
                    "use_cli = false\nuse_msi = false\n}\n}\n"
                )
                result = subprocess.run(
                    ["terraform", "init", "-input=false", "-no-color"],
                    check=False,
                    cwd=native,
                    env=environment,
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                if result.returncode:
                    raise RuntimeError(
                        f"Synthetic native backend fixture failed: {result.stderr}"
                    )
                checks.assertEqual(seen, {"backend", "vault"})
            finally:
                proxy.terminate()
                proxy.wait(timeout=10)
                server.shutdown()
                thread.join(timeout=12)
            checks.assertFalse(thread.is_alive(), "TLS fixture thread did not finish")
    print(
        "Actual Squid ACL, unchanged TLS peer, native backend and pinned Vault SDK passed"
    )


if __name__ == "__main__":
    main()
