from __future__ import annotations


def ollama_unreachable_message(base_url: str) -> str:
    return (
        f"Ollama is unreachable at {base_url}. Install and start Ollama, verify the service is "
        "running, then retry provisioning."
    )


def checkpoint_pull_failed_message(model_tag: str, detail: str | None = None) -> str:
    suffix = f" Detail: {detail}" if detail else ""
    return (
        f"Ollama could not pull model '{model_tag}'. Confirm the model tag is valid, ensure "
        "internet access is available for Ollama, then retry deployment."
        f"{suffix}"
    )
