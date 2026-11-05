# Isolated Linux private operator (candidate route, not live acceptance)

This image is separate from the application's Terraform job. It packages
Terraform **1.16.6** with the verified official archive checksum, Azure CLI
**2.80.0**, OpenVPN, Python, OpenSSL, GitHub CLI and the same reviewed `infra`/`scripts`
source. It does not change the job's Terraform 1.9.8 pin, run a job entrypoint,
apply infrastructure, connect a VPN or contain credentials. Debian packages
and Python transitive dependencies are not fully locked: retain the resulting
image digest and exact source revision for an accepted execution; rebuilding
later is not a byte-for-byte reproduction.

## Permission and capability boundary

No affirmative Windows certificate-store/client/settings approval exists.
Do not install a client or certificate, change host routes/DNS, enable a new
Docker/WSL engine or start an unowned/remote engine. First verify **on the actual
operator machine** that Docker Desktop already exists, is owned/authorized,
uses Linux containers, and its context points to that engine. A cloud runner's
Docker/TUN success is not evidence about the user's Windows machine.

The proposed runtime needs only `NET_ADMIN` and `/dev/net/tun` in the
container namespace. Never add `--privileged`, host networking, host PID,
Docker socket mounts or host device creation as a workaround. Read-only root
filesystem, all other capabilities dropped and `no-new-privileges` are required.
`NET_ADMIN` lets the process change **container** networking and is a meaningful
permission: independently review this boundary before actual use.

Build from a clean reviewed commit, not the canonical private Terraform
directory. The following Bash commands build an archive of tracked public
source only, without collecting local state, plans, overrides or keys:

```bash
revision=REVIEWED_FULL_COMMIT_SHA
mkdir operator-source
git archive "$revision" infra scripts tools/private_operator |
  tar -x -C operator-source
docker build --platform linux/amd64 --build-arg "SOURCE_REVISION=$revision" \
  -f operator-source/tools/private_operator/Dockerfile \
  -t llmserving-private-operator:reviewed operator-source
docker image inspect llmserving-private-operator:reviewed \
  --format '{{.Id}} {{index .Config.Labels "org.opencontainers.image.revision"}}'
```

Run the credential-free capability test on that **same local engine** first.
It creates and closes only a nonpersistent TUN device in an isolated network
namespace, without contacting Azure or touching host routes:

```bash
docker run --rm --network none --cap-drop ALL --cap-add NET_ADMIN \
  --device /dev/net/tun --read-only --security-opt no-new-privileges \
  --tmpfs /tmp --tmpfs /run --tmpfs /root \
  llmserving-private-operator:reviewed \
  python /opt/llmserving/operator-smoke.py --tun
```

An absent/denied device or non-Linux engine is an explicit blocker, not permission
to change the host. Pin the accepted local image ID for subsequent execution.
CI tests this sandbox boundary and tool versions only, not a real VPN.

## Actual execution remains gated

Use the **same** reviewed `infra/operator_access` P2S gateway/resolver/endpoint,
not duplicate resources. Its actual native plan, independent ARM cleanup
arming, cost and allocation gates must pass before any apply.

Generate short-lived certificates in restricted local files. Mount only the
specific private certificate/profile directory read-only and the canonical
private Terraform directory read-write (plus its independently restricted
second backup if required). Never mount a home directory, existing Azure CLI
cache, host certificate store, Docker socket or unrelated source/state.
Verify host ACLs **before** mounting: Linux bind-mount mode bits do not prove
Windows ACL privacy. Preserve the authoritative local state and second
verified backups outside the container; deleting the container is not backup.

Do not log/copy client keys, profile inline keys, plans, state or secret values.
Review the downloaded official certificate/OpenVPN profile locally; reject
profile scripts/plugins and `up`/`down` hooks rather than executing arbitrary
downloaded commands. Profile credentials stay local files, never command-line
arguments, image layers or ARM payloads. Establish the official OpenVPN
connection within the container; use its resolver `10.20.31.4` with container
DNS (never host DNS/hosts-file changes). Log in independently using device-code
or interactive Azure CLI login with the intended tenant/subscription; its
`/run/azure` cache is ephemeral. Do not copy cached host credentials.
Helpers requiring GitHub cleanup-run verification also need an independent
GitHub CLI login in the ephemeral container home; never mount the host's
GitHub CLI cache or pass a token in command-line arguments.

No launcher or live readiness is claimed here. Actual client-profile
compatibility, DNS over P2S, private state/vault TLS, OAuth/lease operations and
the native control plan remain acceptance gates. Private blob connectivity
does not establish state migration or restore. If the local engine cannot meet
the restricted runtime boundary, stop without weakening governance or auth.
