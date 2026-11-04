import { useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { Body1, Button, Field, Input, makeStyles, tokens } from '@fluentui/react-components';
import ConfigVersionHistory from '../components/ConfigVersionHistory';
import EnvironmentPicker from '../components/EnvironmentPicker';
import { ApiError } from '../services/apiClient';
import { listCatalog } from '../services/catalogApi';
import {
  createDeployment,
  createInferenceConfiguration,
  getDeploymentRevision,
  listInferenceConfigurations,
  listModelConfigurations,
} from '../services/deploymentsApi';
import { getEnvironment } from '../services/environmentsApi';
import type {
  DemoEnvironment,
  DeploymentAcceptanceResponse,
  DeploymentRevision,
  InferenceConfigurationVersion,
  ModelCatalogEntry,
  ModelConfigurationVersion,
} from '../services/types';
import {
  DataList,
  EmptyState,
  HuggingFaceTokenField,
  InfoGrid,
  InfoPanel,
  LoadingState,
  PageHeader,
  RouterButton,
  RouterLink,
  SectionCard,
  StatusMessage,
  formatStateLabel,
} from '../components/kit';

const useStyles = makeStyles({
  stack: {
    display: 'flex',
    flexDirection: 'column',
    gap: tokens.spacingVerticalL,
  },
  formGrid: {
    display: 'grid',
    gap: tokens.spacingHorizontalM,
    gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))',
  },
  actions: {
    display: 'flex',
    gap: tokens.spacingHorizontalS,
    flexWrap: 'wrap',
    alignItems: 'center',
  },
  list: {
    margin: 0,
    paddingLeft: tokens.spacingHorizontalL,
    display: 'flex',
    flexDirection: 'column',
    gap: tokens.spacingVerticalXXS,
  },
});

const DEPLOYMENT_POLL_INTERVAL_MS = 2000;
const DEFAULT_GPU_MEMORY_UTILIZATION = '0.9';
const DEFAULT_MAX_MODEL_LEN = '8192';
const DEFAULT_TEMPERATURE = '0.2';
const DEFAULT_TOP_P = '0.95';
const DEFAULT_MAX_TOKENS = '512';

function formatTimestamp(value?: string | null) {
  if (!value) {
    return 'n/a';
  }

  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString();
}

function isFiniteNumberString(value: string) {
  return Number.isFinite(Number(value));
}

function getRetuneErrorMessage(error: unknown) {
  if (error instanceof ApiError) {
    switch (error.code) {
      case 'environment_locked':
      case 'environment_busy':
        return 'This environment is busy with another operation. Wait for it to finish, then retry the retune.';
      case 'hf_token_required':
        return 'The selected checkpoint still requires a Hugging Face token before redeployment can start.';
      default:
        return error.message;
    }
  }

  return error instanceof Error ? error.message : 'Retune request failed.';
}

function applyInferenceSettings(
  configuration: InferenceConfigurationVersion | undefined,
  setGpuMemoryUtilization: (value: string) => void,
  setMaxModelLen: (value: string) => void,
  setTemperature: (value: string) => void,
  setTopP: (value: string) => void,
  setMaxTokens: (value: string) => void,
) {
  setGpuMemoryUtilization(
    String(configuration?.servingSettings.gpu_memory_utilization ?? DEFAULT_GPU_MEMORY_UTILIZATION),
  );
  setMaxModelLen(String(configuration?.servingSettings.max_model_len ?? DEFAULT_MAX_MODEL_LEN));
  setTemperature(String(configuration?.generationSettings.temperature ?? DEFAULT_TEMPERATURE));
  setTopP(String(configuration?.generationSettings.top_p ?? DEFAULT_TOP_P));
  setMaxTokens(String(configuration?.generationSettings.max_tokens ?? DEFAULT_MAX_TOKENS));
}

export default function RetunePage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [catalogEntries, setCatalogEntries] = useState<ModelCatalogEntry[]>([]);
  const [catalogError, setCatalogError] = useState<string>();
  const [environmentId, setEnvironmentId] = useState(searchParams.get('environmentId') ?? '');
  const [environment, setEnvironment] = useState<DemoEnvironment>();
  const [environmentLoading, setEnvironmentLoading] = useState(false);
  const [environmentError, setEnvironmentError] = useState<string>();
  const [contextLoading, setContextLoading] = useState(false);
  const [contextError, setContextError] = useState<string>();
  const [activeDeploymentRevision, setActiveDeploymentRevision] = useState<DeploymentRevision>();
  const [selectedModelConfiguration, setSelectedModelConfiguration] =
    useState<ModelConfigurationVersion>();
  const [selectedInferenceConfiguration, setSelectedInferenceConfiguration] =
    useState<InferenceConfigurationVersion>();
  const [gpuMemoryUtilization, setGpuMemoryUtilization] = useState(DEFAULT_GPU_MEMORY_UTILIZATION);
  const [maxModelLen, setMaxModelLen] = useState(DEFAULT_MAX_MODEL_LEN);
  const [temperature, setTemperature] = useState(DEFAULT_TEMPERATURE);
  const [topP, setTopP] = useState(DEFAULT_TOP_P);
  const [maxTokens, setMaxTokens] = useState(DEFAULT_MAX_TOKENS);
  const [huggingFaceToken, setHuggingFaceToken] = useState('');
  const [deploying, setDeploying] = useState(false);
  const [deploymentError, setDeploymentError] = useState<string>();
  const [deploymentAcceptance, setDeploymentAcceptance] =
    useState<DeploymentAcceptanceResponse>();
  const [deploymentRevision, setDeploymentRevision] = useState<DeploymentRevision>();
  const [historyRefreshToken, setHistoryRefreshToken] = useState(0);

  const activeDeploymentRevisionId =
    environment?.activeDeploymentRevisionId ?? environment?.activeRevisionId ?? '';
  const selectedModelConfigId =
    selectedModelConfiguration?.modelConfigId ?? activeDeploymentRevision?.modelConfigId ?? '';
  const engineId =
    activeDeploymentRevision?.engineId ?? (environment?.provider === 'local' ? 'ollama' : 'vllm');
  const isLocalProvider = engineId === 'ollama';
  const currentDeploymentRevision = activeDeploymentRevision;
  const selectedCatalogEntry = useMemo(
    () => catalogEntries.find((entry) => entry.id === selectedModelConfiguration?.catalogEntryId),
    [catalogEntries, selectedModelConfiguration?.catalogEntryId],
  );
  const requiresHfToken = Boolean(selectedCatalogEntry?.gated);
  const inputFieldsValid = Boolean(
    isFiniteNumberString(temperature) &&
      isFiniteNumberString(topP) &&
      isFiniteNumberString(maxTokens) &&
      (isLocalProvider ||
        (isFiniteNumberString(gpuMemoryUtilization) && isFiniteNumberString(maxModelLen))),
  );
  const canRedeploy = Boolean(
    environment?.environmentId &&
      activeDeploymentRevision &&
      selectedModelConfigId &&
      inputFieldsValid &&
      !deploying &&
      (!requiresHfToken || huggingFaceToken.trim()),
  );

  useEffect(() => {
    let cancelled = false;

    async function loadCatalog() {
      try {
        const response = await listCatalog();

        if (!cancelled) {
          setCatalogEntries(response.entries);
        }
      } catch (error) {
        if (!cancelled) {
          setCatalogError(error instanceof Error ? error.message : 'Failed to load model catalog.');
        }
      }
    }

    void loadCatalog();

    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!environment?.environmentId || !activeDeploymentRevisionId) {
      setContextLoading(false);
      setContextError(undefined);
      setActiveDeploymentRevision(undefined);
      setSelectedModelConfiguration(undefined);
      setSelectedInferenceConfiguration(undefined);
      return;
    }

    let active = true;
    const currentEnvironmentId = environment.environmentId;

    async function loadActiveContext() {
      setContextLoading(true);
      setContextError(undefined);

      try {
        const [revision, modelResponse, inferenceResponse] = await Promise.all([
          getDeploymentRevision(currentEnvironmentId, activeDeploymentRevisionId),
          listModelConfigurations(currentEnvironmentId),
          listInferenceConfigurations(currentEnvironmentId),
        ]);

        if (!active) {
          return;
        }

        const currentModelConfiguration = modelResponse.items.find(
          (configuration) => configuration.modelConfigId === revision.modelConfigId,
        );
        const currentInferenceConfiguration = inferenceResponse.items.find(
          (configuration) => configuration.inferenceConfigId === revision.inferenceConfigId,
        );

        setActiveDeploymentRevision(revision);
        setSelectedModelConfiguration(currentModelConfiguration);
        setSelectedInferenceConfiguration(currentInferenceConfiguration);
        applyInferenceSettings(
          currentInferenceConfiguration,
          setGpuMemoryUtilization,
          setMaxModelLen,
          setTemperature,
          setTopP,
          setMaxTokens,
        );
      } catch (error) {
        if (active) {
          setContextError(
            error instanceof Error
              ? error.message
              : 'Failed to load the active deployment context.',
          );
          setActiveDeploymentRevision(undefined);
          setSelectedModelConfiguration(undefined);
          setSelectedInferenceConfiguration(undefined);
        }
      } finally {
        if (active) {
          setContextLoading(false);
        }
      }
    }

    void loadActiveContext();

    return () => {
      active = false;
    };
  }, [activeDeploymentRevisionId, environment?.environmentId]);

  useEffect(() => {
    if (!deploymentAcceptance?.deploymentRevisionId || !environment?.environmentId) {
      return;
    }

    let active = true;
    let timeoutId: number | undefined;

    const poll = async () => {
      try {
        const nextRevision = await getDeploymentRevision(
          environment.environmentId,
          deploymentAcceptance.deploymentRevisionId,
        );

        if (!active) {
          return;
        }

        setDeploymentRevision(nextRevision);

        if (['ready', 'deployment_failed', 'superseded'].includes(nextRevision.lifecycleState)) {
          setDeploying(false);
          const refreshedEnvironment = await getEnvironment(environment.environmentId);

          if (active) {
            setEnvironment(refreshedEnvironment);
            setHistoryRefreshToken((value) => value + 1);
          }
          return;
        }

        timeoutId = window.setTimeout(poll, DEPLOYMENT_POLL_INTERVAL_MS);
      } catch (error) {
        if (!active) {
          return;
        }

        setDeploymentError(
          error instanceof Error ? error.message : 'Failed to poll the deployment revision.',
        );
        setDeploying(false);
      }
    };

    void poll();

    return () => {
      active = false;
      if (timeoutId !== undefined) {
        window.clearTimeout(timeoutId);
      }
    };
  }, [deploymentAcceptance?.deploymentRevisionId, environment?.environmentId]);

  async function handleLoadEnvironment(nextEnvironmentId: string = environmentId) {
    if (!nextEnvironmentId.trim()) {
      setEnvironmentError('Select an environment to load the active deployment context.');
      return;
    }

    setEnvironmentLoading(true);
    setEnvironmentError(undefined);

    try {
      const nextEnvironment = await getEnvironment(nextEnvironmentId.trim());
      setEnvironment(nextEnvironment);
      setEnvironmentId(nextEnvironment.environmentId);
      setSearchParams({ environmentId: nextEnvironment.environmentId });
      setContextError(undefined);
      setDeploymentAcceptance(undefined);
      setDeploymentRevision(undefined);
      setDeploymentError(undefined);
      setHuggingFaceToken('');
    } catch (error) {
      setEnvironmentError(
        error instanceof Error ? error.message : 'Failed to load the selected environment.',
      );
      setEnvironment(undefined);
    } finally {
      setEnvironmentLoading(false);
    }
  }

  useEffect(() => {
    if (environmentId.trim()) {
      void handleLoadEnvironment(environmentId.trim());
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function handleSelectInferenceConfiguration(configuration: InferenceConfigurationVersion) {
    setSelectedInferenceConfiguration(configuration);
    applyInferenceSettings(
      configuration,
      setGpuMemoryUtilization,
      setMaxModelLen,
      setTemperature,
      setTopP,
      setMaxTokens,
    );
  }

  async function handleRedeploy() {
    if (!environment?.environmentId || !activeDeploymentRevision || !selectedModelConfigId) {
      return;
    }

    setDeploying(true);
    setDeploymentError(undefined);
    setDeploymentAcceptance(undefined);
    setDeploymentRevision(undefined);

    try {
      const nextInferenceConfiguration = await createInferenceConfiguration(environment.environmentId, {
        engineId,
        servingSettings: isLocalProvider
          ? {}
          : {
              gpu_memory_utilization: Number(gpuMemoryUtilization),
              max_model_len: Number(maxModelLen),
            },
        generationSettings: {
          temperature: Number(temperature),
          top_p: Number(topP),
          max_tokens: Number(maxTokens),
        },
      });

      setSelectedInferenceConfiguration(nextInferenceConfiguration);
      setHistoryRefreshToken((value) => value + 1);

      const acceptance = await createDeployment(environment.environmentId, {
        modelConfigId: selectedModelConfigId,
        inferenceConfigId: nextInferenceConfiguration.inferenceConfigId,
        huggingFaceToken: requiresHfToken ? huggingFaceToken.trim() || undefined : undefined,
      });

      setDeploymentAcceptance(acceptance);
    } catch (error) {
      setDeploymentError(getRetuneErrorMessage(error));
      setDeploying(false);
    } finally {
      setHuggingFaceToken('');
    }
  }

  const styles = useStyles();

  return (
    <div className={styles.stack}>
      <PageHeader
        eyebrow="Operate"
        title="Retune an active deployment"
        description="Start from the currently deployed configuration, revise the inference knobs, save a new immutable version, and redeploy it onto the same environment."
      />

      {catalogError ? <StatusMessage intent="error">{catalogError}</StatusMessage> : null}

      <SectionCard title="1. Active environment">
        <div className={styles.formGrid}>
          <EnvironmentPicker
            value={environmentId}
            onSelect={(nextEnvironmentId) => {
              setEnvironmentId(nextEnvironmentId);
              if (nextEnvironmentId) {
                void handleLoadEnvironment(nextEnvironmentId);
              }
            }}
            disabled={environmentLoading}
          />
        </div>

        {environmentError ? <StatusMessage intent="error">{environmentError}</StatusMessage> : null}
        <div className={styles.actions}>
          <Button onClick={() => void handleLoadEnvironment()} disabled={environmentLoading}>
            {environmentLoading ? 'Loading environment…' : 'Reload environment'}
          </Button>
          {environment?.environmentId ? (
            <RouterLink to={`/environments/${environment.environmentId}`}>
              Open environment detail
            </RouterLink>
          ) : null}
        </div>

        {environment ? (
          <InfoGrid>
            <InfoPanel title="Deployment context">
              <DataList
                items={[
                  { label: 'Environment id', value: environment.environmentId },
                  { label: 'Profile', value: environment.profileId },
                  { label: 'Region', value: environment.region },
                  { label: 'Lifecycle', value: formatStateLabel(environment.state) },
                  {
                    label: 'Active deployment revision',
                    value: activeDeploymentRevisionId || 'None yet',
                  },
                ]}
              />
            </InfoPanel>
            <InfoPanel title="Current revision details">
              {contextLoading ? (
                <LoadingState label="Loading active deployment context…" />
              ) : activeDeploymentRevision ? (
                <DataList
                  items={[
                    { label: 'Model configuration', value: activeDeploymentRevision.modelConfigId },
                    {
                      label: 'Inference configuration',
                      value: activeDeploymentRevision.inferenceConfigId,
                    },
                    { label: 'Engine', value: activeDeploymentRevision.engineId },
                    {
                      label: 'Health status',
                      value: formatStateLabel(activeDeploymentRevision.health.status),
                    },
                  ]}
                />
              ) : (
                <Body1>
                  Load an environment with an active deployment to prefill the retune form.
                </Body1>
              )}
            </InfoPanel>
          </InfoGrid>
        ) : null}

        {contextError ? <StatusMessage intent="error">{contextError}</StatusMessage> : null}
        {environment && !activeDeploymentRevisionId ? (
          <StatusMessage intent="warning" title="Deploy before you retune">
            This environment does not have an active deployment revision yet. Open{' '}
            <RouterLink to={`/deploy?environmentId=${encodeURIComponent(environment.environmentId)}`}>
              Deploy
            </RouterLink>{' '}
            first so the retune form has a real configuration to start from.
          </StatusMessage>
        ) : null}
      </SectionCard>

      <SectionCard
        title="2. Revise inference settings"
        description="Retune the serving and generation settings. The form starts from the active inference configuration so you can make a focused adjustment instead of rebuilding from scratch."
      >
        {!environment ? (
          <EmptyState title="Select an environment first">
            Choose the environment whose active deployment you want to retune.
          </EmptyState>
        ) : !activeDeploymentRevisionId ? (
          <EmptyState
            title="No active deployment to retune"
            actions={
              <RouterButton appearance="primary" to={`/deploy?environmentId=${encodeURIComponent(environment.environmentId)}`}>
                Go to Deploy
              </RouterButton>
            }
          >
            Retune works only after the environment already has an active deployment revision.
          </EmptyState>
        ) : contextLoading ? (
          <LoadingState label="Loading the active inference settings…" />
        ) : currentDeploymentRevision ? (
          <>
            <InfoGrid>
              <InfoPanel title="Currently selected versions">
                <DataList
                  items={[
                    {
                      label: 'Model configuration',
                      value: selectedModelConfigId || currentDeploymentRevision.modelConfigId,
                    },
                    {
                      label: 'Inference configuration base',
                      value:
                        selectedInferenceConfiguration?.inferenceConfigId ??
                        currentDeploymentRevision.inferenceConfigId,
                    },
                    { label: 'Engine', value: engineId },
                    {
                      label: 'Checkpoint',
                      value:
                        selectedModelConfiguration?.resolvedCheckpointRef ??
                        selectedCatalogEntry?.checkpoint ??
                        'n/a',
                    },
                  ]}
                />
              </InfoPanel>
              <InfoPanel title="Tip">
                <Body1>
                  Use the configuration history below to start from an older version if you want to
                  retry a previously safe setting mix. The redeploy step will still create a brand new
                  inference configuration version for this retune.
                </Body1>
              </InfoPanel>
            </InfoGrid>

            <div className={styles.formGrid}>
              {!isLocalProvider ? (
                <>
                  <Field label="GPU memory utilization">
                    <Input
                      aria-label="GPU memory utilization"
                      type="number"
                      min={0}
                      max={1}
                      step={0.01}
                      value={gpuMemoryUtilization}
                      onChange={(event) => setGpuMemoryUtilization(event.target.value)}
                    />
                  </Field>
                  <Field label="Max model length">
                    <Input
                      aria-label="Max model length"
                      type="number"
                      min={1}
                      step={1}
                      value={maxModelLen}
                      onChange={(event) => setMaxModelLen(event.target.value)}
                    />
                  </Field>
                </>
              ) : null}
              <Field label="Temperature">
                <Input
                  aria-label="Temperature"
                  type="number"
                  min={0}
                  step={0.01}
                  value={temperature}
                  onChange={(event) => setTemperature(event.target.value)}
                />
              </Field>
              <Field label="Top p">
                <Input
                  aria-label="Top p"
                  type="number"
                  min={0}
                  max={1}
                  step={0.01}
                  value={topP}
                  onChange={(event) => setTopP(event.target.value)}
                />
              </Field>
              <Field label="Max tokens">
                <Input
                  aria-label="Max tokens"
                  type="number"
                  min={1}
                  step={1}
                  value={maxTokens}
                  onChange={(event) => setMaxTokens(event.target.value)}
                />
              </Field>
            </div>

            {!inputFieldsValid ? (
              <StatusMessage intent="warning">
                Enter valid numeric values for every retune field before you redeploy.
              </StatusMessage>
            ) : null}
          </>
        ) : (
          <EmptyState title="Active deployment details unavailable">
            Reload the environment to recover the active deployment context before retuning it.
          </EmptyState>
        )}
      </SectionCard>

      {environment?.environmentId && activeDeploymentRevisionId ? (
        <ConfigVersionHistory
          environmentId={environment.environmentId}
          refreshToken={historyRefreshToken}
          selectedInferenceConfigId={selectedInferenceConfiguration?.inferenceConfigId}
          selectedModelConfigId={selectedModelConfigId || undefined}
          onSelectInferenceConfiguration={handleSelectInferenceConfiguration}
          onSelectModelConfiguration={setSelectedModelConfiguration}
        />
      ) : null}

      <SectionCard
        title="3. Redeploy"
        description="Save the revised inference settings as a new version, then redeploy that version against the selected model configuration."
      >
        {!environment || !activeDeploymentRevisionId ? (
          <EmptyState title="Load an active deployment first">
            Once an environment has an active deployment revision, the retune flow will let you save
            and redeploy a new inference configuration from it.
          </EmptyState>
        ) : currentDeploymentRevision ? (
          <>
            <InfoGrid>
              <InfoPanel title="Redeploy inputs">
                <DataList
                  items={[
                    {
                      label: 'Model configuration to keep',
                      value: selectedModelConfigId || currentDeploymentRevision.modelConfigId,
                    },
                    { label: 'Engine', value: engineId },
                    {
                      label: 'New inference version source',
                      value:
                        selectedInferenceConfiguration?.inferenceConfigId ??
                        currentDeploymentRevision.inferenceConfigId,
                    },
                    {
                      label: 'Checkpoint access',
                      value: requiresHfToken ? 'Gated Hugging Face access required' : 'Open checkpoint',
                    },
                  ]}
                />
              </InfoPanel>
              <InfoPanel title="What happens next">
                <Body1 block>
                  The button below first creates a brand new inference configuration version, then
                  starts a new deployment revision using the chosen model configuration.
                </Body1>
                {requiresHfToken ? (
                  <HuggingFaceTokenField
                    value={huggingFaceToken}
                    onChange={setHuggingFaceToken}
                    huggingFaceRepoId={selectedCatalogEntry?.huggingFaceRepo}
                  />
                ) : (
                  <Body1>No Hugging Face token is required for this model configuration.</Body1>
                )}
              </InfoPanel>
            </InfoGrid>

            {deploymentError ? <StatusMessage intent="error">{deploymentError}</StatusMessage> : null}
            <div className={styles.actions}>
              <Button appearance="primary" onClick={() => void handleRedeploy()} disabled={!canRedeploy}>
                {deploying ? 'Redeploying…' : 'Create new inference version and redeploy'}
              </Button>
            </div>

            {deploymentAcceptance ? (
              <InfoGrid>
                <InfoPanel title="Deployment status">
                  <DataList
                    items={[
                      { label: 'Operation id', value: deploymentAcceptance.operationId },
                      {
                        label: 'Revision id',
                        value: deploymentAcceptance.deploymentRevisionId,
                      },
                      {
                        label: 'Lifecycle',
                        value: formatStateLabel(
                          deploymentRevision?.lifecycleState ?? deploymentAcceptance.lifecycleState,
                        ),
                      },
                    ]}
                  />
                  {deploymentRevision?.lifecycleState === 'ready' ? (
                    <StatusMessage intent="success">
                      Redeployment ready. The environment is now serving the newly retuned settings.
                    </StatusMessage>
                  ) : null}
                  {deploymentRevision?.lifecycleState === 'deployment_failed' ? (
                    <StatusMessage intent="error">
                      Redeployment failed. Review the diagnostics before trying another retune.
                    </StatusMessage>
                  ) : null}
                </InfoPanel>
                <InfoPanel title="Health diagnostics">
                  {deploymentRevision ? (
                    <>
                      <Body1 block>Status: {formatStateLabel(deploymentRevision.health.status)}</Body1>
                      {deploymentRevision.health.diagnostics.length ? (
                        <ul className={styles.list}>
                          {deploymentRevision.health.diagnostics.map((item) => (
                            <li key={item}>
                              <Body1>{item}</Body1>
                            </li>
                          ))}
                        </ul>
                      ) : (
                        <Body1>No deployment diagnostics reported.</Body1>
                      )}
                      <Body1 block>
                        Active from {formatTimestamp(deploymentRevision.activePeriod.startedAt)} to{' '}
                        {formatTimestamp(deploymentRevision.activePeriod.endedAt)}
                      </Body1>
                    </>
                  ) : (
                    <Body1>Waiting for the first deployment status poll.</Body1>
                  )}
                </InfoPanel>
              </InfoGrid>
            ) : null}

            {deploymentRevision?.lifecycleState === 'ready' && environment.environmentId ? (
              <div className={styles.actions}>
                <RouterButton
                  appearance="primary"
                  to={`/exercise?environmentId=${encodeURIComponent(environment.environmentId)}`}
                >
                  Next: exercise the retuned deployment
                </RouterButton>
              </div>
            ) : null}
          </>
        ) : (
          <EmptyState title="Active deployment details unavailable">
            Reload the environment to recover the current deployment inputs before redeploying.
          </EmptyState>
        )}
      </SectionCard>
    </div>
  );
}
