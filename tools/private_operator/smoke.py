"""Credential-free packaged tool and isolated TUN capability smoke."""

import argparse
import fcntl
import json
import os
import struct
import subprocess
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tun", action="store_true")
    args = parser.parse_args()
    terraform = json.loads(
        subprocess.check_output(["terraform", "version", "-json"], text=True)
    )
    if terraform["terraform_version"] != "1.16.6":
        raise RuntimeError("Authoritative operator requires Terraform 1.16.6")
    azure = json.loads(subprocess.check_output(["az", "version"], text=True))
    if azure["azure-cli"] != "2.80.0":
        raise RuntimeError("Operator Azure CLI version differs from reviewed pin")
    subprocess.run(["openvpn", "--version"], check=True, stdout=subprocess.DEVNULL)
    subprocess.run(["gh", "--version"], check=True, stdout=subprocess.DEVNULL)
    for module in ("bootstrap", "shared", "control", "demo", "operator_access"):
        if not Path(f"/opt/llmserving/infra/{module}/main.tf").is_file():
            raise RuntimeError(f"Missing packaged native module: {module}")
    if not Path("/opt/llmserving/scripts/app_bootstrap.py").is_file():
        raise RuntimeError("Missing packaged app bootstrap helper")
    if args.tun:
        # TUNSETIFF creates a nonpersistent device only in this container's namespace.
        with open("/dev/net/tun", "r+b", buffering=0) as tun:
            fcntl.ioctl(tun, 0x400454CA, struct.pack("16sH", b"llmtest0", 0x1001))
            if not Path("/sys/class/net/llmtest0").is_dir():
                raise RuntimeError("TUN device was not created")
        if Path("/sys/class/net/llmtest0").exists():
            raise RuntimeError("Nonpersistent smoke device was not removed")
    if os.environ.get("AZURE_CONFIG_DIR") != "/run/azure":
        raise RuntimeError("Azure login cache must be isolated inside the container")
    print("Packaged tool smoke passed" + ("; isolated TUN passed" if args.tun else ""))


if __name__ == "__main__":
    main()
