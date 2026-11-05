FROM python:3.12-slim-bookworm@sha256:0f086103b026048cc50cb5da25ec435c023c5241a83fc44daea593377abc61c4 AS network

ARG SOURCE_REVISION
LABEL org.opencontainers.image.revision="${SOURCE_REVISION}"

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates openvpn iproute2 openssl squid \
    && rm -rf /var/lib/apt/lists/*
COPY tools/private_proxy/squid.conf /etc/llmserving/squid.conf
COPY tools/private_proxy/hosts.txt /etc/llmserving/hosts.txt
WORKDIR /work
CMD ["sleep", "infinity"]

FROM network AS runtime
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl unzip gh \
    && curl --fail --silent --show-error --location \
        https://releases.hashicorp.com/terraform/1.16.6/terraform_1.16.6_linux_amd64.zip \
        --output /tmp/terraform.zip \
    && echo '38034b38d03096399a7a1264a14561a8029b2b496fd1f169452656e53968f1b7  /tmp/terraform.zip' | sha256sum --check --strict \
    && unzip /tmp/terraform.zip terraform -d /usr/local/bin \
    && rm /tmp/terraform.zip \
    && apt-get purge -y unzip \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir azure-cli==2.80.0

COPY infra /opt/llmserving/infra
COPY scripts /opt/llmserving/scripts
COPY tools/private_operator/smoke.py /opt/llmserving/operator-smoke.py
COPY tools/private_proxy/smoke.py /opt/llmserving/proxy-smoke.py
ENV AZURE_CONFIG_DIR=/run/azure \
    CHECKPOINT_DISABLE=1 \
    TF_IN_AUTOMATION=true
WORKDIR /work
CMD ["/bin/bash"]
