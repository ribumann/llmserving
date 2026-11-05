"""Staged, operator-run main application bootstrap; never deploys infrastructure."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import http.client
import json
import os
from pathlib import Path
import re
import ssl
import subprocess
import zipfile

from release_bundle import IMAGES, file_hash

SUBSCRIPTION = "86677b6e-28fc-48e4-8988-5ab9e568eece"
TENANT = "ecd6dfda-d2ce-47a8-9901-e35f31fe18dd"
CLIENT = "962740a1-be3e-454f-87c3-537ed1f02b78"
ROOT = f"/subscriptions/{SUBSCRIPTION}/resourceGroups/"
SHARED = ROOT + "rg-llmserving-e2e-shared"
ENVIRONMENT = (
    ROOT + "rg-llmserving-e2e-control"
    "/providers/Microsoft.App/managedEnvironments/llmrelease-cae"
)
APP_PATH = f"/v1.0/applications(appId='{CLIENT}')"
SECRET_NAME = "sso-client-secret"


class BootstrapError(ValueError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise BootstrapError(message)


def load_contract(path: Path) -> dict:
    contract = json.loads(path.read_text())
    require(
        type(contract) is dict
        and set(contract) == {
            "acr_login_server", "vault_name", "images", "functions_zip",
            "functions_sha256", "allowed_email_domains", "operator_upn",
        },
        "Supply exactly the documented application input fields.",
    )
    registry = contract["acr_login_server"]
    require(
        type(registry) is str
        and re.fullmatch(r"[a-z0-9]{5,50}\.azurecr\.io", registry) is not None,
        "Use the shared Azure registry login server.",
    )
    require(
        type(contract["vault_name"]) is str
        and re.fullmatch(r"[a-z][a-z0-9-]{1,22}[a-z0-9]", contract["vault_name"])
        is not None,
        "Use the shared private vault name.",
    )
    images = contract["images"]
    require(type(images) is dict and set(images) == set(IMAGES),
            "Exactly seven image components are required.")
    for image in images.values():
        require(
            type(image) is str
            and re.fullmatch(
                re.escape(registry) + r"/[a-z0-9]+(?:[._/-][a-z0-9]+)*@sha256:[0-9a-f]{64}",
                image,
            ) is not None,
            "Every image must use the shared registry and a registry pull digest, not a tag/config digest.",
        )
    domains = contract["allowed_email_domains"]
    require(
        type(domains) is list and bool(domains)
        and all(type(domain) is str for domain in domains)
        and len(set(domains)) == len(domains)
        and all(
            re.fullmatch(r"(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z]{2,63}", domain)
            is not None and domain not in {"example.com", "example.net", "example.org"}
            for domain in domains
        ),
        "Supply explicit lowercase operator email domains; no placeholders/wildcards.",
    )
    upn = contract["operator_upn"]
    require(
        type(upn) is str and re.fullmatch(r"[A-Za-z0-9._%+-]+@[^@]+", upn) is not None
        and upn.rsplit("@", 1)[1].lower() in domains,
        "The approved operator UPN domain must be in the explicit email allowlist.",
    )
    require(
        type(contract["functions_zip"]) is str
        and type(contract["functions_sha256"]) is str
        and re.fullmatch(r"[0-9a-f]{64}", contract["functions_sha256"]) is not None,
        "Supply the reviewed local Functions ZIP and SHA-256.",
    )
    package = Path(contract["functions_zip"])
    if not package.is_absolute():
        package = path.parent / package
    require(package.suffix == ".zip" and file_hash(package) == contract["functions_sha256"],
            "Functions ZIP checksum mismatch.")
    require(zipfile.is_zipfile(package), "Functions package must be an actual ZIP.")
    with zipfile.ZipFile(package) as archive:
        require({"host.json", "function_app.py"} <= set(archive.namelist()),
                "Functions ZIP must contain host.json and function_app.py at its root.")
    contract["functions_zip"] = str(package.absolute())
    return contract


def control_inputs(contract: dict) -> dict:
    return {
        "subscription_id": SUBSCRIPTION,
        "enable_sso": True,
        "existing_sso_client_id": CLIENT,
        "existing_sso_tenant_id": TENANT,
        "existing_sso_secret_id": f"https://{contract['vault_name']}.vault.azure.net/secrets/{SECRET_NAME}",
        "auth_allowed_email_domains": ",".join(contract["allowed_email_domains"]),
        "functions_package_sha256": contract["functions_sha256"],
        "manage_database_url_secret": True,
        **{f"{name}_image": image for name, image in contract["images"].items()},
    }


def az_json(*arguments: str) -> object:
    try:
        result = subprocess.run(
            ["az", *arguments, "--subscription", SUBSCRIPTION,
             "--only-show-errors", "--output", "json"],
            capture_output=True, check=False, timeout=90,
        )
        require(result.returncode == 0,
                "Azure CLI operation failed; inspect permissions/connectivity privately. Raw diagnostics suppressed.")
        return json.loads(result.stdout)
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError):
        raise BootstrapError("Azure CLI unavailable, timed out or returned invalid JSON.") from None


def read_arm(resource_id: str, api: str) -> dict:
    result = az_json("rest", "--method", "GET", "--url",
                     f"https://management.azure.com{resource_id}?api-version={api}")
    require(type(result) is dict and result.get("id", "").lower() == resource_id.lower(),
            "ARM returned a different resource.")
    return result


def preview(contract: dict, *, callbacks: bool = True) -> dict:
    account = az_json("account", "show", "--subscription", SUBSCRIPTION)
    require(
        type(account) is dict and account.get("id") == SUBSCRIPTION
        and account.get("tenantId") == TENANT,
        "The selected subscription/tenant does not match main.",
    )
    redirects = []
    if callbacks:
        environment = read_arm(ENVIRONMENT, "2023-05-01")
        props = environment.get("properties", {})
        require(props.get("provisioningState") == "Succeeded",
                "The full reviewed control deployment must create the CAE first.")
        domain = props.get("defaultDomain")
        require(
            type(domain) is str
            and re.fullmatch(r"[a-z0-9-]+(?:\.[a-z0-9-]+)+\.azurecontainerapps\.io", domain) is not None,
            "The CAE must supply its real Azure default domain.",
        )
        redirects = [
            f"https://llmrelease-{name}.{domain}/.auth/login/aad/callback"
            for name in ("frontend", "backend")
        ]
    registry = contract["acr_login_server"].removesuffix(".azurecr.io")
    acr = read_arm(SHARED + "/providers/Microsoft.ContainerRegistry/registries/" + registry,
                   "2023-07-01")
    require(acr.get("properties", {}).get("loginServer") == contract["acr_login_server"],
            "Image registry does not belong to the shared stack.")
    vault_id = SHARED + "/providers/Microsoft.KeyVault/vaults/" + contract["vault_name"]
    vault = read_arm(vault_id, "2023-07-01")
    vault_props = vault.get("properties", {})
    require(
        vault_props.get("tenantId") == TENANT
        and vault_props.get("publicNetworkAccess") == "Disabled"
        and vault_props.get("enableRbacAuthorization") is True
        and vault_props.get("vaultUri", "").rstrip("/")
        == f"https://{contract['vault_name']}.vault.azure.net",
        "The shared vault must be private-only, RBAC-enabled and in the approved tenant.",
    )
    app = az_json(
        "rest", "--method", "GET", "--url",
        f"https://graph.microsoft.com{APP_PATH}?$select=appId,signInAudience,web,passwordCredentials",
    )
    require(
        type(app) is dict and app.get("appId") == CLIENT
        and app.get("signInAudience") == "AzureADMyOrg",
        "The explicitly approved isolated application must be single-tenant.",
    )
    web = app.get("web")
    require(type(web) is dict, "Application web metadata unavailable.")
    current = web.get("redirectUris", [])
    require(
        type(current) is list and all(uri in redirects for uri in current),
        "Application has foreign redirects; stop rather than reuse a production application.",
    )
    grant = web.get("implicitGrantSettings", {})
    require(type(grant) is dict, "Malformed application token configuration.")
    credentials = app.get("passwordCredentials")
    require(
        type(credentials) is list and all(
            type(item) is dict and type(item.get("keyId")) is str
            and re.fullmatch(r"[0-9a-fA-F-]{36}", item["keyId"]) is not None
            for item in credentials
        ),
        "Application credential metadata unavailable or malformed.",
    )
    return {
        "subscription_id": SUBSCRIPTION, "tenant_id": TENANT, "client_id": CLIENT,
        "phase": "callbacks" if callbacks else "initial-secret",
        "environment_id": ENVIRONMENT if callbacks else None, "vault_id": vault_id,
        "callbacks": redirects,
        "current_redirects": current,
        "current_id_token_issuance": grant.get("enableIdTokenIssuance", False),
        "current_access_token_issuance": grant.get("enableAccessTokenIssuance", False),
        "control_tfvars": control_inputs(contract),
        "functions_zip": contract["functions_zip"],
        "functions_sha256": contract["functions_sha256"],
        "operator_upn": contract["operator_upn"],
        "existing_credential_key_ids": sorted(item["keyId"] for item in credentials),
        "new_credential": {
            "displayName": "main-container-apps-easy-auth",
            "endDateTime": (
                datetime.now(timezone.utc).date() + timedelta(days=90)
            ).isoformat() + "T00:00:00Z",
        },
    }


def approval_hash(plan: dict) -> str:
    return hashlib.sha256(json.dumps(plan, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def azure_token(resource: str) -> str:
    token = az_json("account", "get-access-token", "--tenant", TENANT, "--resource", resource)
    require(type(token) is dict and type(token.get("accessToken")) is str
            and bool(token["accessToken"]), "Azure did not return an access token.")
    return token["accessToken"]


def request_json(
    host: str, path: str, method: str, token: str, payload: dict,
    *, read_response: bool = False,
) -> object:
    # No redirect following, proxy subprocess, HTTP diagnostics or response-body logging.
    connection = http.client.HTTPSConnection(host, timeout=30, context=ssl.create_default_context())
    try:
        connection.request(method, path, body=json.dumps(payload).encode(),
                           headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
        response = connection.getresponse()
        require(200 <= response.status < 300,
                f"Azure {method} failed (HTTP {response.status}); response suppressed. Mutation outcome may be partial.")
        if read_response:
            raw = response.read(65537)
            require(len(raw) <= 65536, "Azure response too large; inspect app credential metadata before retrying.")
            try:
                return json.loads(raw)
            except (ValueError, UnicodeDecodeError):
                raise BootstrapError("Azure response malformed; inspect app credential metadata before retrying.") from None
        return None
    except (OSError, http.client.HTTPException):
        raise BootstrapError("Azure request failed; response suppressed. Inspect remote state before retrying.") from None
    finally:
        connection.close()


def mutate(operation: str, contract: dict, plan: dict, secret_fd: int | None) -> None:
    if operation == "set-callbacks":
        request_json(
            "graph.microsoft.com", APP_PATH, "PATCH",
            azure_token("https://graph.microsoft.com"),
            {"web": {
                "redirectUris": plan["callbacks"],
                "implicitGrantSettings": {
                    "enableIdTokenIssuance": True,
                    "enableAccessTokenIssuance": plan["current_access_token_issuance"],
                },
            }},
        )
        return
    if operation == "create-secret":
        require(plan["existing_credential_key_ids"] == [],
                "Initial credential creation requires no existing passwords; inspect rather than rotating blindly.")
        # Acquire both scoped tokens before creating any one-time credential.
        vault_token = azure_token("https://vault.azure.net")
        graph_token = azure_token("https://graph.microsoft.com")
        credential = request_json(
            "graph.microsoft.com", APP_PATH + "/addPassword", "POST", graph_token,
            {"passwordCredential": plan["new_credential"]}, read_response=True,
        )
        require(
            type(credential) is dict and type(credential.get("keyId")) is str
            and re.fullmatch(r"[0-9a-fA-F-]{36}", credential["keyId"]) is not None
            and type(credential.get("secretText")) is str and bool(credential["secretText"]),
            "Credential response malformed; inspect app password metadata before retrying. No secret has been logged.",
        )
        try:
            request_json(
                f"{contract['vault_name']}.vault.azure.net",
                f"/secrets/{SECRET_NAME}?api-version=7.4", "PUT", vault_token,
                {"value": credential["secretText"], "contentType": "Entra application client secret"},
            )
        except BootstrapError:
            raise BootstrapError(
                "Credential created but vault write unverified. Do not retry creation. "
                f"Inspect vault privately and remove only new app credential key ID {credential['keyId']} "
                "if recovery requires a fresh credential. Secret suppressed."
            ) from None
        return
    require(secret_fd is not None and secret_fd >= 0,
            "Supply an already approved application's credential over --secret-fd, never argv/env.")
    require(not os.isatty(secret_fd), "Do not type credentials into an echoed terminal.")
    # Read a bounded credential from an operator-owned pipe/FD; no file or subprocess receives it.
    with os.fdopen(os.dup(secret_fd), "rb") as stream:
        raw = stream.read(4097)
    require(0 < len(raw) <= 4096, "Credential must be nonempty and at most 4096 bytes.")
    try:
        secret = raw.decode("utf-8").removesuffix("\n")
    except UnicodeDecodeError:
        raise BootstrapError("Credential must be UTF-8.") from None
    require(bool(secret) and all(32 <= ord(char) <= 126 for char in secret),
            "Credential contains invalid characters.")
    request_json(
        f"{contract['vault_name']}.vault.azure.net",
        f"/secrets/{SECRET_NAME}?api-version=7.4", "PUT",
        azure_token("https://vault.azure.net"),
        {"value": secret, "contentType": "Entra application client secret"},
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=(
        "validate", "preview-secret", "create-secret", "store-secret", "preview-callbacks", "set-callbacks",
    ))
    parser.add_argument("--inputs", type=Path, required=True)
    parser.add_argument("--approve-preview-sha256")
    parser.add_argument("--secret-fd", type=int)
    args = parser.parse_args()
    try:
        contract = load_contract(args.inputs)
        if args.operation == "validate":
            print(json.dumps({"control_tfvars": control_inputs(contract),
                              "functions_zip": contract["functions_zip"],
                              "functions_sha256": contract["functions_sha256"]}, indent=2))
            return
        plan = preview(contract, callbacks=args.operation in {"preview-callbacks", "set-callbacks"})
        digest = approval_hash(plan)
        if args.operation.startswith("preview-"):
            print(json.dumps({"preview_sha256": digest, **plan}, indent=2))
            return
        require(args.approve_preview_sha256 == digest,
                "Live preview differs or exact preview approval is missing; rerun preview and review.")
        mutate(args.operation, contract, plan, args.secret_fd)
        print(f"{args.operation} completed; infrastructure and browser acceptance remain unverified.")
    except (BootstrapError, ValueError, TypeError, OSError, KeyError) as exc:
        # Never interpolate arbitrary input/SDK exception text into operator logs.
        message = str(exc) if isinstance(exc, BootstrapError) else "Invalid or unreadable bootstrap input."
        raise SystemExit(f"Application bootstrap blocked: {message}") from None


if __name__ == "__main__":
    main()
