from __future__ import annotations

from src.config import get_settings
from src.domain.catalog import ModelCatalogEntry
from src.domain.enums import ModelFamily, ModelSizeClass, ProviderType
from src.domain.inference_engine import InferenceEngine
from src.domain.profile import CloudDeploymentProfile
from src.persistence.db import create_session_factory

PROFILE_IDS = {
    ModelSizeClass.THREE_B: ["azure-single-gpu-3b"],
    ModelSizeClass.SEVEN_B: ["azure-single-gpu-7b"],
    ModelSizeClass.SEVENTY_B: ["azure-single-gpu-70b"],
}

PROFILE_IDS[ModelSizeClass.THREE_B].append("local-ollama")

CATALOG_ENTRIES = [
    {
        "catalogEntryId": "gemma-3-4b-it",
        "family": ModelFamily.GEMMA,
        "sizeClass": ModelSizeClass.THREE_B,
        "huggingFaceRepoId": "google/gemma-3-4b-it",
        "checkpointRef": "main",
        "isGated": True,
        "license": "Gemma ToS",
        "compatibleProfileIds": PROFILE_IDS[ModelSizeClass.THREE_B],
        "quantizationRequired": False,
        "notes": "Gemma 3 small slot; instruction-tuned and multimodal.",
    },
    {
        "catalogEntryId": "gemma-3-12b-it",
        "family": ModelFamily.GEMMA,
        "sizeClass": ModelSizeClass.SEVEN_B,
        "huggingFaceRepoId": "google/gemma-3-12b-it",
        "checkpointRef": "main",
        "isGated": True,
        "license": "Gemma ToS",
        "compatibleProfileIds": PROFILE_IDS[ModelSizeClass.SEVEN_B],
        "quantizationRequired": False,
        "notes": "Gemma medium slot; selected because Gemma 3 has no native 7B checkpoint.",
    },
    {
        "catalogEntryId": "gemma-3-27b-it",
        "family": ModelFamily.GEMMA,
        "sizeClass": ModelSizeClass.SEVENTY_B,
        "huggingFaceRepoId": "google/gemma-3-27b-it",
        "checkpointRef": "main",
        "isGated": True,
        "license": "Gemma ToS",
        "compatibleProfileIds": PROFILE_IDS[ModelSizeClass.SEVENTY_B],
        "quantizationRequired": True,
        "notes": "Gemma large slot; quantization recommended for demo stability.",
    },
    {
        "catalogEntryId": "llama-3.2-3b-instruct",
        "family": ModelFamily.LLAMA,
        "sizeClass": ModelSizeClass.THREE_B,
        "huggingFaceRepoId": "meta-llama/Llama-3.2-3B-Instruct",
        "checkpointRef": "main",
        "isGated": True,
        "license": "Llama Community License",
        "compatibleProfileIds": PROFILE_IDS[ModelSizeClass.THREE_B],
        "quantizationRequired": False,
        "notes": "Llama small slot for edge and on-device framing.",
    },
    {
        "catalogEntryId": "llama-3.1-8b-instruct",
        "family": ModelFamily.LLAMA,
        "sizeClass": ModelSizeClass.SEVEN_B,
        "huggingFaceRepoId": "meta-llama/Llama-3.1-8B-Instruct",
        "checkpointRef": "main",
        "isGated": True,
        "license": "Llama Community License",
        "compatibleProfileIds": PROFILE_IDS[ModelSizeClass.SEVEN_B],
        "quantizationRequired": False,
        "notes": "Llama medium slot; quality and cost workhorse checkpoint.",
    },
    {
        "catalogEntryId": "llama-3.3-70b-instruct",
        "family": ModelFamily.LLAMA,
        "sizeClass": ModelSizeClass.SEVENTY_B,
        "huggingFaceRepoId": "meta-llama/Llama-3.3-70B-Instruct",
        "checkpointRef": "main",
        "isGated": True,
        "license": "Llama Community License",
        "compatibleProfileIds": PROFILE_IDS[ModelSizeClass.SEVENTY_B],
        "quantizationRequired": True,
        "notes": "Flagship Llama slot; requires quantization on single-GPU hosting.",
    },
    {
        "catalogEntryId": "qwen3-4b",
        "family": ModelFamily.CHINESE_ORIGIN,
        "sizeClass": ModelSizeClass.THREE_B,
        "huggingFaceRepoId": "Qwen/Qwen3-4B",
        "checkpointRef": "main",
        "isGated": False,
        "license": "Apache 2.0",
        "compatibleProfileIds": PROFILE_IDS[ModelSizeClass.THREE_B],
        "quantizationRequired": False,
        "notes": "Ungated Chinese-origin small slot.",
    },
    {
        "catalogEntryId": "qwen2.5-0.5b-instruct",
        "family": ModelFamily.CHINESE_ORIGIN,
        "sizeClass": ModelSizeClass.THREE_B,
        "huggingFaceRepoId": "Qwen/Qwen2.5-0.5B-Instruct",
        "checkpointRef": "qwen2.5:0.5b-instruct",
        "isGated": False,
        "license": "Apache 2.0",
        "compatibleProfileIds": ["local-ollama"],
        "quantizationRequired": False,
        "notes": "Small Ollama-friendly Qwen checkpoint for local demo mode.",
    },
    {
        "catalogEntryId": "qwen3-8b",
        "family": ModelFamily.CHINESE_ORIGIN,
        "sizeClass": ModelSizeClass.SEVEN_B,
        "huggingFaceRepoId": "Qwen/Qwen3-8B",
        "checkpointRef": "main",
        "isGated": False,
        "license": "Apache 2.0",
        "compatibleProfileIds": PROFILE_IDS[ModelSizeClass.SEVEN_B],
        "quantizationRequired": False,
        "notes": "Ungated medium slot with broad multilingual coverage.",
    },
    {
        "catalogEntryId": "qwen3-32b",
        "family": ModelFamily.CHINESE_ORIGIN,
        "sizeClass": ModelSizeClass.SEVENTY_B,
        "huggingFaceRepoId": "Qwen/Qwen3-32B",
        "checkpointRef": "main",
        "isGated": False,
        "license": "Apache 2.0",
        "compatibleProfileIds": PROFILE_IDS[ModelSizeClass.SEVENTY_B],
        "quantizationRequired": False,
        "notes": "Preferred large Qwen slot because it fits an 80 GB GPU without quantization.",
    },
    {
        "catalogEntryId": "phi-3.5-mini-instruct",
        "family": ModelFamily.PHI,
        "sizeClass": ModelSizeClass.THREE_B,
        "huggingFaceRepoId": "microsoft/Phi-3.5-mini-instruct",
        "checkpointRef": "main",
        "isGated": False,
        "license": "MIT",
        "compatibleProfileIds": PROFILE_IDS[ModelSizeClass.THREE_B],
        "quantizationRequired": False,
        "notes": "Ungated Phi small slot; strong reasoning-per-parameter for its size class.",
    },
    {
        "catalogEntryId": "phi-4",
        "family": ModelFamily.PHI,
        "sizeClass": ModelSizeClass.SEVEN_B,
        "huggingFaceRepoId": "microsoft/phi-4",
        "checkpointRef": "main",
        "isGated": False,
        "license": "MIT",
        "compatibleProfileIds": PROFILE_IDS[ModelSizeClass.SEVEN_B],
        "quantizationRequired": False,
        "notes": "Ungated Phi medium slot; 14B dense model tuned for math/reasoning benchmarks.",
    },
    {
        "catalogEntryId": "phi-3.5-moe-instruct",
        "family": ModelFamily.PHI,
        "sizeClass": ModelSizeClass.SEVENTY_B,
        "huggingFaceRepoId": "microsoft/Phi-3.5-MoE-instruct",
        "checkpointRef": "main",
        "isGated": False,
        "license": "MIT",
        "compatibleProfileIds": PROFILE_IDS[ModelSizeClass.SEVENTY_B],
        "quantizationRequired": True,
        "notes": (
            "Phi large slot; 41.9B-parameter mixture-of-experts (6.6B active) standing in for a "
            "70B-class checkpoint since Phi has no dense model at that scale."
        ),
    },
]

ENGINE_RECORD = {
    "engineId": "vllm",
    "adapterContractVersion": "2026-08-19",
    "capabilities": {
        "deploymentImage": "vllm/vllm-openai",
        "openAiCompatible": True,
        "quantizationModes": ["awq", "gptq", "fp8", "int4", "gguf"],
        "metricsEndpoints": ["/metrics", "/health"],
        "maxModelSizeClass": "70b",
    },
}

OLLAMA_ENGINE_RECORD = {
    "engineId": "ollama",
    "adapterContractVersion": "2026-08-19",
    "capabilities": {
        "deploymentImage": None,
        "openAiCompatible": True,
        "quantizationModes": ["gguf"],
        "metricsEndpoints": ["/api/tags", "/v1/chat/completions"],
        "maxModelSizeClass": "3b",
    },
}

PROFILE_RECORDS = [
    {
        "profileId": "azure-single-gpu-3b",
        "provider": ProviderType.AZURE,
        "modelSizeClass": ModelSizeClass.THREE_B,
        "eligibleRegions": [
            "polandcentral",
            "eastus2",
            "southcentralus",
            "westus3",
            "westeurope",
            "northeurope",
        ],
        "vmSku": "Standard_NC16as_T4_v3",
        "capacityAssumptions": {"gpuCount": 1, "gpuMemoryGb": 16, "quantizationRequired": False},
        "configurableInputs": {
            "profileSizeClass": "small",
            "bootstrapModelRepo": "Qwen/Qwen3-4B",
            "adminUsername": "azureuser",
            "allowedSshSourceCidr": "",
            "allowedApiSourceCidr": "",
        },
        "knownLimitations": [
            "Quota and SKU checks reduce risk but do not guarantee physical GPU capacity."
        ],
        "version": 1,
    },
    {
        "profileId": "azure-single-gpu-7b",
        "provider": ProviderType.AZURE,
        "modelSizeClass": ModelSizeClass.SEVEN_B,
        "eligibleRegions": [
            "polandcentral",
            "eastus2",
            "southcentralus",
            "westus3",
            "westeurope",
            "northeurope",
        ],
        "vmSku": "Standard_NC16as_T4_v3",
        "capacityAssumptions": {"gpuCount": 1, "gpuMemoryGb": 16, "quantizationRequired": False},
        "configurableInputs": {
            "profileSizeClass": "small",
            "bootstrapModelRepo": "Qwen/Qwen3-8B",
            "adminUsername": "azureuser",
            "allowedSshSourceCidr": "",
            "allowedApiSourceCidr": "",
        },
        "knownLimitations": [
            "Quota and SKU checks reduce risk but do not guarantee physical GPU capacity."
        ],
        "version": 1,
    },
    {
        "profileId": "azure-single-gpu-70b",
        "provider": ProviderType.AZURE,
        "modelSizeClass": ModelSizeClass.SEVENTY_B,
        "eligibleRegions": [
            "eastus2",
            "southcentralus",
            "westus3",
            "westeurope",
            "northeurope",
        ],
        "vmSku": "Standard_NC80adis_H100_v5",
        "capacityAssumptions": {"gpuCount": 2, "gpuMemoryGb": 188, "quantizationRequired": True},
        "configurableInputs": {
            "profileSizeClass": "large",
            "bootstrapModelRepo": "Qwen/Qwen3-32B",
            "adminUsername": "azureuser",
            "vllmExtraArgs": ["--quantization", "awq"],
            "allowedSshSourceCidr": "",
            "allowedApiSourceCidr": "",
        },
        "knownLimitations": [
            "Large-profile deployments may still fail with AllocationFailed even when quota "
            "checks pass.",
            "Quantization may be required for some 70B checkpoints.",
        ],
        "version": 1,
    },
    {
        "profileId": "local-ollama",
        "provider": ProviderType.LOCAL,
        "modelSizeClass": ModelSizeClass.THREE_B,
        "eligibleRegions": [],
        "vmSku": "local-machine",
        "capacityAssumptions": {
            "gpuCount": 0,
            "gpuMemoryGb": None,
            "hardwareProfile": "Commodity CPU or single consumer GPU",
            "quantizationRequired": False,
        },
        "configurableInputs": {},
        "knownLimitations": [
            "Local runs depend on presenter-managed hardware and a reachable Ollama runtime."
        ],
        "version": 1,
    },
]


def main() -> None:
    settings = get_settings()
    session_factory = create_session_factory(settings)
    with session_factory() as session:
        session.merge(InferenceEngine(**ENGINE_RECORD))
        session.merge(InferenceEngine(**OLLAMA_ENGINE_RECORD))
        for payload in PROFILE_RECORDS:
            session.merge(CloudDeploymentProfile(**payload))
        for payload in CATALOG_ENTRIES:
            session.merge(ModelCatalogEntry(**payload))
        session.commit()

    print(
        "Seeded "
        f"{len(PROFILE_RECORDS)} deployment profiles, "
        f"{len(CATALOG_ENTRIES)} model catalog entries, "
        "and the vllm/ollama inference engines."
    )


if __name__ == "__main__":
    main()
