import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from validate_retained_group_plan import PlanRejected, canonical_saved_backend


class SavedBackendTests(unittest.TestCase):
    def test_exact_pinned_backend_and_reject_redirect_remote_workspace(self):
        expected = bytes.fromhex(
            "0a056c6f63616c12180a1682a470617468c0ad776f726b73706163655f646972c0"
            "1a0764656661756c74"
        )
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "plan"
            for value, accepted in (
                (b"\x6a" + bytes([len(expected)]) + expected, True),
                (
                    b"\x6a"
                    + bytes([len(expected)])
                    + expected.replace(b"local", b"other"),
                    False,
                ),
                (
                    b"\x6a"
                    + bytes([len(expected)])
                    + expected.replace(b"default", b"foreign"),
                    False,
                ),
                (b"\x6a" + bytes([len(expected)]) + expected + b"\xea\x01\x00", False),
                (b"\x6a\xff", False),
            ):
                with zipfile.ZipFile(path, "w") as archive:
                    archive.writestr("tfplan", value)
                if accepted:
                    canonical_saved_backend(path)
                else:
                    with self.assertRaises(PlanRejected):
                        canonical_saved_backend(path)

    @unittest.skipUnless(
        os.environ.get("TEST_NATIVE_BACKEND") == "true",
        "explicit native binary contract job",
    )
    def test_real_terraform_1166_default_and_redirected_backend(self):
        terraform = shutil.which("terraform")
        self.assertIsNotNone(terraform)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name, backend in (
                ("canonical", ""),
                ("redirected", 'backend "local" {\npath = "elsewhere.tfstate"\n}\n'),
            ):
                module = root / name
                module.mkdir()
                (module / "main.tf").write_text(
                    'terraform {\nrequired_version = "= 1.16.6"\n' + backend + "}\n"
                )
                subprocess.run(
                    [terraform, "init", "-input=false", "-no-color"],
                    cwd=module,
                    check=True,
                    stdout=subprocess.DEVNULL,
                )
                subprocess.run(
                    [terraform, "plan", "-input=false", "-no-color", "-out=plan"],
                    cwd=module,
                    check=True,
                    stdout=subprocess.DEVNULL,
                )
                if name == "canonical":
                    canonical_saved_backend(module / "plan")
                else:
                    with self.assertRaises(PlanRejected):
                        canonical_saved_backend(module / "plan")


if __name__ == "__main__":
    unittest.main()
