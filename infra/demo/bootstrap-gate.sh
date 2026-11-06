#!/bin/sh
# Custom Script v2 runs this observer, never cloud-init itself.
set -eu

# Terminate only the status observer on timeout, not cloud-init/APT/dpkg.
if timeout --kill-after=10s 1500 cloud-init status --wait; then
  :
else
  rc=$?
  echo "GPU bootstrap gate: cloud-init failed or readiness wait timed out (exit $rc)." >&2
  exit "$rc"
fi

if [ ! -f /opt/llmserving/bootstrap.ready ] || [ -f /opt/llmserving/bootstrap.failed ]; then
  echo "GPU bootstrap gate: successful runtime bootstrap was not confirmed." >&2
  exit 1
fi

echo "GPU bootstrap gate ready; managed NVIDIA driver installation may start."
