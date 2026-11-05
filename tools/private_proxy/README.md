# Private CONNECT mode: host authentication, container networking only

This mode uses the `network` build target of the existing reviewed
`tools/private_operator/Dockerfile`, adding **Squid** rather than a token broker.
It contains no Azure CLI, GitHub CLI, Terraform, native modules or pip install.
The existing full operator target remains separate for CI SDK/backend tests.
Windows retains canonical Terraform
**1.16.6**, all native state/inputs/backups and its existing Azure CLI SSO.
Only short-lived OpenVPN certificate/key/profile files enter the container,
read-only. **No state, Azure/GitHub CLI cache, user home or Docker socket is
mounted.** No new Azure identity, device login, host CA installation, Windows
VPN client, persistent proxy setting, host DNS or route change is needed.

The bundled configuration permits only **CONNECT on port 443** to exactly:

```
llmreleasestate0ea5e6.blob.core.windows.net
llmrelease-kv-0ea5e6.vault.azure.net
```

No wildcards, suffix subdomains, IP literals, plaintext HTTP, management/login
hosts or arbitrary destinations are allowed. A distinct future control vault
requires an independently reviewed **exact** hostname addition, frozen before
launch; never widen to `.vault.azure.net`. Squid resolves names inside the
container via the private inbound resolver **10.20.31.4**. There is no
`ssl_bump`, generated interception certificate, TLS termination or token
handling in Squid. Client TLS verification/SNI stays end-to-end to Azure.
Access logging is disabled; administrative errors stay in container tmpfs.

## Prerequisites and launch boundary

The coordinator has verified an actual local Docker Desktop Linux engine and
isolated TUN creation without changing Windows VPN/certificate-store/routes.
That is not yet a VPN connection or private data-plane acceptance.
The same seven-resource `infra/operator_access` module still needs an exact
private native plan and successfully armed independent cleanup **before apply**.
Never duplicate its gateway or weaken storage/vault public-network policy.

Build **only the network target**, not the default full operator image, from an
exact reviewed commit's tracked archive. No PyPI access is needed for this
target. The pinned base is AMD64: on ARM64 Docker Desktop use
`--platform linux/amd64` emulation. Record the source revision and local image
ID, and verify OpenVPN/Squid and isolated TUN on that engine. Mutable apt
packages mean the resulting
image ID, not merely the Dockerfile, identifies the accepted build.

```bash
mkdir proxy-source
git archive REVIEWED_FULL_COMMIT_SHA tools/private_operator/Dockerfile tools/private_proxy |
  tar -x -C proxy-source
docker build --target network --platform linux/amd64 \
  --build-arg SOURCE_REVISION=REVIEWED_FULL_COMMIT_SHA \
  -f proxy-source/tools/private_operator/Dockerfile \
  -t llmserving-private-proxy:reviewed proxy-source
```

Launch with a name unique to this attempt and the actual restricted certificate
directory, using the accepted image ID. Docker's `--mount` fails if the source
does not exist. These examples use Bash syntax; Windows operators must retain
the same literal arguments and verified absolute path.

```bash
docker run --detach --name llmserving-private-vpn \
  --platform linux/amd64 --user 0 --cap-drop ALL --cap-add NET_ADMIN \
  --device /dev/net/tun --read-only --security-opt no-new-privileges \
  --tmpfs /tmp --tmpfs /run --tmpfs /root \
  --publish 127.0.0.1::3128 \
  --mount type=bind,src=RESTRICTED_ABSOLUTE_CERT_DIRECTORY,dst=/vpn,readonly \
  ACCEPTED_IMAGE_ID sleep infinity
docker port llmserving-private-vpn 3128/tcp
```

Confirm the port output is **127.0.0.1 only**, never `0.0.0.0` or `::`.
Do not use host networking, `--privileged`, extra capabilities, socket mounts
or host device creation. The loopback proxy is accessible to other local
processes: it is not a per-user authentication boundary. Shut it down promptly.

Review the official OpenVPN certificate profile locally first: reject plugin,
script, management-interface, alternate configuration/include or `up/down`
hooks. Keep private keys/profile inline keys off command lines/logs. Use only
the actual approved gateway and supplied certificate paths. Start the
connection attached in one terminal (no daemon or persistence):

```bash
docker exec -it --user 0 llmserving-private-vpn \
  openvpn --config /vpn/client.ovpn --script-security 0 \
  --pull-filter 'ignore redirect-gateway' --auth-nocache
```

Verify connection success and pushed/installed VNet routes **inside** the
container, including reachability of `10.20.31.4`. Do not accept pushed scripts
or change host routing. Then start the proxy attached in a second terminal:

```bash
docker exec --user 13:13 llmserving-private-vpn \
  squid -N -f /etc/llmserving/squid.conf
```

The Debian `proxy` user is UID/GID 13; Squid runs without requiring SETUID,
SETGID or other additional container capabilities. DNS failure is a blocker,
not permission to add public fallback DNS/host entries. No fixture hosts
entries or fixture CA may be used for real operations.

## Host-side operations: scope proxy variables carefully

Do **not** export `HTTPS_PROXY` for the whole Terraform apply. AzureRM makes
ARM and CLI token-refresh requests too, which the exact private allowlist
intentionally rejects. Go/Python standard proxy selection is per destination,
but a normal `NO_PROXY` list cannot express "all hosts except these two".

The verified narrow mode is for commands that contact only the two private
endpoints, such as a separate backend connectivity/lease probe or a Key Vault
data-plane operation using an already-valid host token. Execute each in a
fresh child process with `HTTPS_PROXY=http://127.0.0.1:ACTUAL_PORT`, and clear
conflicting lowercase proxy variables and `NO_PROXY` for that child only.
Keep tokens out of arguments, output and container mounts. Environment changes
must disappear when the child exits, including failures.

For a mixed control operation, the standard environment-proxy mechanism can
keep a **frozen reviewed public bypass list** in the child process's `NO_PROXY`,
while the proxy permits only the private endpoints. An initial candidate is
`management.azure.com,login.microsoftonline.com,graph.microsoft.com`.
Verify those public destinations already use an authorized direct route:
do not bypass an existing required organizational proxy. Anything not in that
public list goes through Squid and fails unless it is one of the two exact
private hosts. `NO_PROXY` must never include `*`, the private hosts, `.azure.net`
or `.core.windows.net`. Clear conflicting lowercase `no_proxy`/`https_proxy`
and set both case variants consistently within the child, then restore them
by exiting the process. Initialize providers beforehand on the normal public
route so registry downloads are outside this mixed operation.

**A full authoritative control apply is not yet verified by these fixtures.**
It additionally requires actual Windows CLI/token-refresh and provider
acceptance with this frozen public bypass list. Unlisted public endpoints must
fail explicitly and be reviewed, not silently added on error.
Never silently fall back to direct private traffic, wildcard the allowlist,
copy host credentials into Linux, or claim a successful private blob probe is
state migration, locking recovery or full-stack deployment.

## Evidence and cleanup

Credential-free CI starts the actual Squid process with no external network,
read-only root and no capabilities. A synthetic TLS server proves rejection
of foreign/subdomain/IP/port/plain-HTTP requests and exact unchanged TLS peer
certificates through CONNECT. Terraform **1.16.6** itself initializes its real
AzureRM backend against a synthetic SAS/blob fixture, and AzureRM **3.117.1**'s
pinned Kermit Key Vault SDK performs an actual secret read through the tunnel.
Python Requests (the packaged CLI transport dependency) is also exercised.
The fixture CA and `/etc/hosts` entries exist only inside this CI container;
there is no real Azure login, state, secret or private VPN. This is not actual
Windows/P2S/DNS acceptance, and the synthetic value is not a real credential.

For real acceptance, retain private evidence of container DNS/private IP,
valid Azure TLS, host-native CLI/SDK proxy success and rejected unrelated
destinations. On cancellation/failure or completion, stop/remove **only this
named container**, verify its loopback listener is absent, and remove only its
short-lived certificate files with appropriate local authorization. Preserve
canonical state and backups. Azure resources remain subject to independent
ARM cleanup; removing this local container does not deprovision the gateway.
