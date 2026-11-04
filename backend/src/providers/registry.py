from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from src.domain.enums import ProviderType
from src.domain.environment import DemoEnvironment
from src.domain.profile import CloudDeploymentProfile
from src.providers.base import ProviderCapabilities, UnsupportedProviderError

PROVIDER_CAPABILITIES = (
    ProviderCapabilities(
        provider=ProviderType.AZURE,
        engines=("vllm",),
        cloudInfrastructure=True,
        durableProvisioning=True,
        durableModelDeployment=True,
        durableEvaluation=False,
    ),
    ProviderCapabilities(
        provider=ProviderType.LOCAL,
        engines=("ollama",),
        cloudInfrastructure=False,
        durableProvisioning=False,
        durableModelDeployment=False,
        durableEvaluation=False,
    ),
)


class CompositeProviderAdapter:
    def __init__(
        self,
        *,
        azure,
        local,
        session_factory: sessionmaker[Session],
    ) -> None:
        self._azure = azure
        self._local = local
        self._session_factory = session_factory

    def previewEnvironment(self, profileId: str, regionOverride: str | None = None):
        return self._for_profile(profileId).previewEnvironment(profileId, regionOverride)

    def preview_with_details(self, *, profileId: str, regionOverride: str | None = None):
        return self._for_profile(profileId).preview_with_details(
            profileId=profileId, regionOverride=regionOverride
        )

    def provisionEnvironment(self, profileId: str, region: str):
        return self._for_profile(profileId).provisionEnvironment(profileId, region)

    def start_provisioning(self, **kwargs):
        profile = kwargs.get("profile")
        provider = self._resolve_by_provider(getattr(profile, "provider", None))
        return provider.start_provisioning(**kwargs)

    def getEnvironmentState(self, environmentId: str):
        return self._for_environment(environmentId).getEnvironmentState(environmentId)

    def deployRevision(
        self,
        environmentId: str,
        modelConfig: Mapping[str, Any],
        inferenceConfig: Mapping[str, Any],
        engineId: str,
    ):
        return self._for_environment(environmentId).deployRevision(
            environmentId, modelConfig, inferenceConfig, engineId
        )

    def start_deployment(self, **kwargs):
        return self._for_environment(str(kwargs["environment_id"])).start_deployment(**kwargs)

    def get_engine_adapter(self, engine_id: str):
        if engine_id == "ollama":
            return self._local.get_engine_adapter(engine_id)
        if engine_id == "vllm":
            return self._azure.get_engine_adapter(engine_id)
        raise LookupError(f"Engine '{engine_id}' is not supported.")

    def teardownPreview(self, environmentId: str):
        return self._for_environment(environmentId).teardownPreview(environmentId)

    def teardownEnvironment(self, environmentId: str, previewToken: str):
        return self._for_environment(environmentId).teardownEnvironment(environmentId, previewToken)

    def _for_profile(self, profile_id: str):
        with self._session_factory() as session:
            profile = session.get(CloudDeploymentProfile, profile_id)
            if profile is None:
                raise LookupError(f"Profile '{profile_id}' was not found.")
            return self._resolve_by_provider(profile.provider)

    def _for_environment(self, environment_id: str):
        with self._session_factory() as session:
            environment = session.get(DemoEnvironment, environment_id)
            if environment is None:
                raise LookupError(f"Environment '{environment_id}' was not found.")
            return self._resolve_by_provider(environment.provider)

    def _resolve_by_provider(self, provider: ProviderType | str | None):
        if provider == ProviderType.LOCAL:
            return self._local
        if provider == ProviderType.AZURE:
            return self._azure
        raise UnsupportedProviderError(f"Provider '{provider}' has no implemented adapter.")
