import re
import unittest
from pathlib import Path


class ControlCustomDomainContractTests(unittest.TestCase):
    def test_only_frontend_custom_domain_is_ignored(self):
        source = (Path(__file__).resolve().parents[2] / "infra" / "control" / "main.tf").read_text(
            encoding="utf-8"
        )
        frontend = source.split('resource "azurerm_container_app" "frontend" {', 1)[1]
        frontend = frontend.split("\n# --- RBAC:", 1)[0]
        ignored = re.search(r"^\s*ignore_changes\s*=\s*\[(.*)\]\s*$", frontend, re.MULTILINE)
        self.assertIsNotNone(ignored)
        self.assertEqual(
            [item.strip() for item in ignored.group(1).split(",")],
            ["template[0].container[0].image", "ingress[0].custom_domain"],
        )
        self.assertEqual(source.count("ingress[0].custom_domain"), 1)

    def test_managed_sso_retains_generated_callbacks_and_appends_extras(self):
        source = (Path(__file__).resolve().parents[2] / "infra" / "control" / "main.tf").read_text(
            encoding="utf-8"
        )
        self.assertRegex(
            source,
            r'sso_redirect_uris\s*=\s*concat\(\[\s*'
            r'"https://\$\{local\.frontend_fqdn\}/\.auth/login/aad/callback",\s*'
            r'"https://\$\{local\.backend_fqdn\}/\.auth/login/aad/callback",\s*'
            r'\],\s*var\.additional_frontend_sso_redirect_uris\)',
        )
        application = source.split('resource "azuread_application" "sso" {', 1)[1]
        application = application.split('resource "azuread_service_principal"', 1)[0]
        self.assertRegex(application, r"redirect_uris\s*=\s*local\.sso_redirect_uris\b")


if __name__ == "__main__":
    unittest.main()
