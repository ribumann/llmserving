import { useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import {
  Body1,
  Button,
  Field,
  Input,
  Select,
  Textarea,
  makeStyles,
  tokens,
} from '@fluentui/react-components';
import ConfigVersionHistory from '../components/ConfigVersionHistory';
import EnvironmentPicker from '../components/EnvironmentPicker';
import { ApiError } from '../services/apiClient';
import { listCatalog } from '../services/catalogApi';
import {
  createDeployment,
  createInferenceConfiguration,
  createModelConfiguration,
  getDeploymentRevision,
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
  HuggingFaceTokenField,
  InfoGrid,
  InfoPanel,
  LoadingState,
  PageHeader,
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
const DEFAULT_MODEL_SETTINGS = JSON.stringify(
  {
    maxContextLength: 8192,
  },
  null,
  2,
);

function formatTimestamp(value?: string | null) {
  if (!value) {
    return 'n/a';
  }

  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString();
}

function parseJsonInput(value: string, fieldName: string) {
  try {
    const parsed = JSON.parse(value) as unknown;

    if (!parsed || Array.isArray(parsed) || typeof parsed !== 'object') {
      throw new Error(`${fieldName} must be a JSON object.`);
    }

    return parsed as Record<string, unknown>;
  } catch (error) {
    throw new Error(error instanceof Error ? error.message : `${fieldName} is invalid JSON.`);
  }
}

function getDeploymentErrorMessage(error: unknown) {
  if (error instanceof ApiError) {
    switch (error.code) {
      case 'environment_locked':
      case 'environment_busy':
        return 'This environment is busy with another operation. Wait for it to finish, then retry deployment.';
      case 'hf_token_required':
        return 'This gated checkpoint requires a Hugging Face token before deployment can start.';
      default:
        return error.message;
    }
  }

  return error instanceof Error ? error.message : 'Deployment failed to start.';
}

export default function DeployPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [catalogEntries, setCatalogEntries] = useState<ModelCatalogEntry[]>([]);
  const [catalogLoading, setCatalogLoading] = useState(true);
  const [catalogError, setCatalogError] = useState<string>();
  const [environmentId, setEnvironmentId] = useState(searchParams.get('environmentId') ?? '');
  const [environment, setEnvironment] = useState<DemoEnvironment>();
  const [environmentLoading, setEnvironmentLoading] = useState(false);
  const [environmentError, setEnvironmentError] = useState<string>();
  const [selectedModelId, setSelectedModelId] = useState('');
  const [resolvedCheckpointRef, setResolvedCheckpointRef] = useState('');
  const [modelSettingsText, setModelSettingsText] = useState(DEFAULT_MODEL_SETTINGS);
  const [savingModelConfig, setSavingModelConfig] = useState(false);
  const [modelConfigError, setModelConfigError] = useState<string>();
  const [selectedModelConfiguration, setSelectedModelConfiguration] =
    useState<ModelConfigurationVersion>();
  const [gpuMemoryUtilization, setGpuMemoryUtilization] = useState('0.9');
  const [maxModelLen, setMaxModelLen] = useState('8192');
  const [temperature, setTemperature] = useState('0.2');
  const [topP, setTopP] = useState('0.95');
  const [maxTokens, setMaxTokens] = useState('512');
  const [savingInferenceConfig, setSavingInferenceConfig] = useState(false);
  const [inferenceConfigError, setInferenceConfigError] = useState<string>();
  const [selectedInferenceConfiguration, setSelectedInferenceConfiguration] =
    useState<InferenceConfigurationVersion>();
  const [huggingFaceToken, setHuggingFaceToken] = useState('');
  const [deploying, setDeploying] = useState(false);
  const [deploymentError, setDeploymentError] = useState<string>();
  const [deploymentAcceptance, setDeploymentAcceptance] = useState<DeploymentAcceptanceResponse>();
  const [deploymentRevision, setDeploymentRevision] = useState<DeploymentRevision>();
  const [historyRefreshToken, setHistoryRefreshToken] = useState(0);

  const compatibleModels = useMemo(() => {
    if (!environment?.profileId) {
      return [];
    }

    return catalogEntries.filter((entry) => entry.compatibleProfileIds.includes(environment.profileId));
  }, [catalogEntries, environment?.profileId]);

  const selectedCatalogEntry = useMemo(
    () => compatibleModels.find((entry) => entry.id === selectedModelId),
    [compatibleModels, selectedModelId],
  );

  const selectedConfigurationCatalogEntry = useMemo(() => {
    const catalogEntryId = selectedModelConfiguration?.catalogEntryId ?? selectedCatalogEntry?.id;
    return catalogEntries.find((entry) => entry.id === catalogEntryId);
  }, [catalogEntries, selectedCatalogEntry?.id, selectedModelConfiguration?.catalogEntryId]);

  const activeDeploymentRevisionId =
    environment?.activeDeploymentRevisionId ?? environment?.activeRevisionId ?? null;
  const isLocalProvider = environment?.provider === 'local';
  const engineId = isLocalProvider ? 'ollama' : 'vllm';

  const canCreateModelConfiguration = Boolean(
    environment?.environmentId &&
      selectedModelId &&
      resolvedCheckpointRef.trim().length > 0 &&
      !savingModelConfig,
  );
  const canCreateInferenceConfiguration = Boolean(environment?.environmentId && !savingInferenceConfig);
  const requiresHfToken = Boolean(selectedConfigurationCatalogEntry?.gated);
  const canDeploy = Boolean(
    environment?.environmentId &&
      selectedModelConfiguration?.modelConfigId &&
      selectedInferenceConfiguration?.inferenceConfigId &&
      !deploying &&
      (!requiresHfToken || huggingFaceToken.trim()),
  );

  useEffect(() => {
    let cancelled = false;

    async function loadCatalog() {
      try {
        const response = await listCatalog();

        if (cancelled) {
          return;
        }

        setCatalogEntries(response.entries);
      } catch (error) {
        if (!cancelled) {
          setCatalogError(error instanceof Error ? error.message : 'Failed to load model catalog.');
        }
      } finally {
        if (!cancelled) {
          setCatalogLoading(false);
        }
      }
    }

    void loadCatalog();

    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!selectedCatalogEntry) {
      return;
    }

    setResolvedCheckpointRef(selectedCatalogEntry.checkpoint);
  }, [selectedCatalogEntry]);

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
      setEnvironmentError('Select an environment to load the ready environment.');
      return;
    }

    setEnvironmentLoading(true);
    setEnvironmentError(undefined);

    try {
      const nextEnvironment = await getEnvironment(nextEnvironmentId.trim());
      setEnvironment(nextEnvironment);
      setSelectedModelId('');
      setSelectedModelConfiguration(undefined);
      setSelectedInferenceConfiguration(undefined);
      setDeploymentAcceptance(undefined);
      setDeploymentRevision(undefined);
      setDeploymentError(undefined);
      setSearchParams({ environmentId: nextEnvironment.environmentId });
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
    // Auto-load the environment carried over via the ?environmentId= deep link so an
    // operator arriving from another page doesn't have to click "Load environment" again.
    if (environmentId.trim()) {
      void handleLoadEnvironment(environmentId.trim());
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function handleCreateModelConfiguration() {
    if (!environment?.environmentId || !selectedModelId) {
      return;
    }

    setSavingModelConfig(true);
    setModelConfigError(undefined);

    try {
      const response = await createModelConfiguration(environment.environmentId, {
        catalogEntryId: selectedModelId,
        resolvedCheckpointRef: resolvedCheckpointRef.trim(),
        modelSettings: parseJsonInput(modelSettingsText, 'Model settings'),
      });

      setSelectedModelConfiguration(response);
      setHistoryRefreshToken((value) => value + 1);
    } catch (error) {
      setModelConfigError(
        error instanceof Error ? error.message : 'Failed to create the model configuration.',
      );
    } finally {
      setSavingModelConfig(false);
    }
  }

  async function handleCreateInferenceConfiguration() {
    if (!environment?.environmentId) {
      return;
    }

    setSavingInferenceConfig(true);
    setInferenceConfigError(undefined);

    try {
      const response = await createInferenceConfiguration(environment.environmentId, {
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

      setSelectedInferenceConfiguration(response);
      setHistoryRefreshToken((value) => value + 1);
    } catch (error) {
      setInferenceConfigError(
        error instanceof Error ? error.message : 'Failed to create the inference configuration.',
      );
    } finally {
      setSavingInferenceConfig(false);
    }
  }

  async function handleDeploy() {
    if (
      !environment?.environmentId ||
      !selectedModelConfiguration?.modelConfigId ||
      !selectedInferenceConfiguration?.inferenceConfigId
    ) {
      return;
    }

    setDeploying(true);
    setDeploymentError(undefined);
    setDeploymentRevision(undefined);

    try {
      const response = await createDeployment(environment.environmentId, {
        modelConfigId: selectedModelConfiguration.modelConfigId,
        inferenceConfigId: selectedInferenceConfiguration.inferenceConfigId,
        huggingFaceToken: huggingFaceToken.trim() || undefined,
      });

      setDeploymentAcceptance(response);
    } catch (error) {
      setDeploymentError(getDeploymentErrorMessage(error));
      setDeploying(false);
    } finally {
      setHuggingFaceToken('');
    }
  }

  function handleSelectModelConfiguration(configuration: ModelConfigurationVersion) {
    setSelectedModelConfiguration(configuration);
    setSelectedModelId(configuration.catalogEntryId);
    setResolvedCheckpointRef(configuration.resolvedCheckpointRef);
    setModelSettingsText(JSON.stringify(configuration.modelSettings, null, 2));
  }

  function handleSelectInferenceConfiguration(configuration: InferenceConfigurationVersion) {
    setSelectedInferenceConfiguration(configuration);
    setGpuMemoryUtilization(String(configuration.servingSettings.gpu_memory_utilization ?? '0.9'));
    setMaxModelLen(String(configuration.servingSettings.max_model_len ?? '8192'));
    setTemperature(String(configuration.generationSettings.temperature ?? '0.2'));
    setTopP(String(configuration.generationSettings.top_p ?? '0.95'));
    setMaxTokens(String(configuration.generationSettings.max_tokens ?? '512'));
  }

  const styles = useStyles();

  return (
    <div className={styles.stack}>
      <PageHeader
        eyebrow="Setup"
        title="Deploy a model revision"
        description="Load a ready environment, create immutable model and inference configuration versions, then explicitly deploy the selected pair."
      />

      {catalogLoading ? <LoadingState label="Loading model catalog…" /> : null}
      {catalogError ? <StatusMessage intent="error">{catalogError}</StatusMessage> : null}

      <SectionCard title="1. Target environment">
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
            <InfoPanel title="Environment state">
              <DataList
                items={[
                  { label: 'Name', value: environment.name ?? environment.environmentId },
                  { label: 'Profile', value: environment.profileId },
                  { label: 'Region', value: environment.region },
                  { label: 'Lifecycle', value: formatStateLabel(environment.state) },
                  { label: 'Active deployment revision', value: activeDeploymentRevisionId ?? 'None yet' },
                ]}
              />
            </InfoPanel>
            <InfoPanel title="Deployment notes">
              <Body1>
                Only catalog entries compatible with the provisioned profile are shown here. Every
                configuration save creates a new version; it will not take effect until you deploy
                it explicitly.
              </Body1>
            </InfoPanel>
          </InfoGrid>
        ) : null}
      </SectionCard>

      {environment ? (
        <>
          <SectionCard title="2. Create model configuration">
            <div className={styles.formGrid}>
              <Field label="Catalog entry">
                <Select
                  value={selectedModelId}
                  onChange={(event) => setSelectedModelId(event.target.value)}
                >
                  <option value="">Select a compatible model</option>
                  {compatibleModels.map((entry) => (
                    <option key={entry.id} value={entry.id}>
                      {entry.family} — {entry.huggingFaceRepo}
                    </option>
                  ))}
                </Select>
              </Field>

              <Field label="Resolved checkpoint ref">
                <Input
                  value={resolvedCheckpointRef}
                  onChange={(event) => setResolvedCheckpointRef(event.target.value)}
                  placeholder="main"
                />
              </Field>
            </div>

            {selectedCatalogEntry ? (
              <InfoGrid>
                <InfoPanel title="Catalog context">
                  <Body1 block>
                    <strong>{selectedCatalogEntry.family}</strong> — {selectedCatalogEntry.huggingFaceRepo}
                  </Body1>
                  <Body1 block>License: {selectedCatalogEntry.license}</Body1>
                  <Body1 block>
                    Access:{' '}
                    {selectedCatalogEntry.gated
                      ? 'Gated Hugging Face access required at deploy time'
                      : 'Open checkpoint'}
                  </Body1>
                  {selectedCatalogEntry.demonstrationValue ? (
                    <Body1 block>{selectedCatalogEntry.demonstrationValue}</Body1>
                  ) : null}
                </InfoPanel>
                <InfoPanel title="Model settings JSON">
                  <Field label="Model settings">
                    <Textarea
                      rows={8}
                      value={modelSettingsText}
                      onChange={(event) => setModelSettingsText(event.target.value)}
                    />
                  </Field>
                </InfoPanel>
              </InfoGrid>
            ) : (
              <Field label="Model settings">
                <Textarea
                  rows={8}
                  value={modelSettingsText}
                  onChange={(event) => setModelSettingsText(event.target.value)}
                />
              </Field>
            )}

            {modelConfigError ? <StatusMessage intent="error">{modelConfigError}</StatusMessage> : null}
            <div className={styles.actions}>
              <Button
                appearance="primary"
                onClick={handleCreateModelConfiguration}
                disabled={!canCreateModelConfiguration}
              >
                {savingModelConfig ? 'Saving model config…' : 'Create model configuration'}
              </Button>
            </div>

            {selectedModelConfiguration ? (
              <StatusMessage intent="success">
                Selected model configuration v{selectedModelConfiguration.version}:{' '}
                {selectedModelConfiguration.modelConfigId}
              </StatusMessage>
            ) : null}
          </SectionCard>

          <SectionCard
            title="3. Create inference configuration"
            description={
              isLocalProvider
                ? 'Ollama is the fixed engine for local environments; GPU serving settings do not apply.'
                : 'vLLM is the fixed engine in v1, so the runtime form exposes its demo-safe defaults.'
            }
          >
            <div className={styles.formGrid}>
              <Field label="Engine">
                <Input value={engineId} disabled readOnly />
              </Field>
              {isLocalProvider ? null : (
                <>
                  <Field label="GPU memory utilization">
                    <Input
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
                      type="number"
                      min={1}
                      step={1}
                      value={maxModelLen}
                      onChange={(event) => setMaxModelLen(event.target.value)}
                    />
                  </Field>
                </>
              )}
              <Field label="Temperature">
                <Input
                  type="number"
                  min={0}
                  step={0.01}
                  value={temperature}
                  onChange={(event) => setTemperature(event.target.value)}
                />
              </Field>
              <Field label="Top p">
                <Input
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
                  type="number"
                  min={1}
                  step={1}
                  value={maxTokens}
                  onChange={(event) => setMaxTokens(event.target.value)}
                />
              </Field>
            </div>

            {inferenceConfigError ? (
              <StatusMessage intent="error">{inferenceConfigError}</StatusMessage>
            ) : null}
            <div className={styles.actions}>
              <Button
                appearance="primary"
                onClick={handleCreateInferenceConfiguration}
                disabled={!canCreateInferenceConfiguration}
              >
                {savingInferenceConfig ? 'Saving inference config…' : 'Create inference configuration'}
              </Button>
            </div>

            {selectedInferenceConfiguration ? (
              <StatusMessage intent="success">
                Selected inference configuration v{selectedInferenceConfiguration.version}:{' '}
                {selectedInferenceConfiguration.inferenceConfigId}
              </StatusMessage>
            ) : null}
          </SectionCard>

          <ConfigVersionHistory
            environmentId={environment.environmentId}
            refreshToken={historyRefreshToken}
            selectedInferenceConfigId={selectedInferenceConfiguration?.inferenceConfigId}
            selectedModelConfigId={selectedModelConfiguration?.modelConfigId}
            onSelectInferenceConfiguration={handleSelectInferenceConfiguration}
            onSelectModelConfiguration={handleSelectModelConfiguration}
          />

          <SectionCard title="4. Deploy selected versions">
            <InfoGrid>
              <InfoPanel title="Selected deployment inputs">
                <DataList
                  items={[
                    { label: 'Model configuration', value: selectedModelConfiguration?.modelConfigId ?? 'Choose or create one' },
                    { label: 'Inference configuration', value: selectedInferenceConfiguration?.inferenceConfigId ?? 'Choose or create one' },
                    { label: 'Checkpoint access', value: requiresHfToken ? 'Gated checkpoint' : 'Open checkpoint' },
                  ]}
                />
              </InfoPanel>
              <InfoPanel title="Deployment behavior">
                <Body1>
                  Deployment is explicit: saving a new config version does not change traffic until
                  you click Deploy.
                </Body1>
                {requiresHfToken ? (
                  <HuggingFaceTokenField
                    value={huggingFaceToken}
                    onChange={setHuggingFaceToken}
                    huggingFaceRepoId={selectedConfigurationCatalogEntry?.huggingFaceRepo}
                  />
                ) : (
                  <Body1>No Hugging Face token is required for the selected configuration.</Body1>
                )}
              </InfoPanel>
            </InfoGrid>

            {deploymentError ? <StatusMessage intent="error">{deploymentError}</StatusMessage> : null}
            <div className={styles.actions}>
              <Button appearance="primary" onClick={handleDeploy} disabled={!canDeploy}>
                {deploying ? 'Deploying…' : 'Deploy selected revision'}
              </Button>
              {environment?.environmentId ? (
                <RouterLink to={`/exercise?environmentId=${environment.environmentId}`}>
                  Open exercise console
                </RouterLink>
              ) : null}
            </div>

            {deploymentAcceptance ? (
              <InfoGrid>
                <InfoPanel title="Deployment status">
                  <DataList
                    items={[
                      { label: 'Operation id', value: deploymentAcceptance.operationId },
                      { label: 'Revision id', value: deploymentAcceptance.deploymentRevisionId },
                      {
                        label: 'Current lifecycle',
                        value: formatStateLabel(
                          deploymentRevision?.lifecycleState ?? deploymentAcceptance.lifecycleState,
                        ),
                      },
                    ]}
                  />
                  {deploymentRevision?.lifecycleState === 'ready' ? (
                    <StatusMessage intent="success">
                      Deployment ready. You can now submit prompts in the Exercise page.
                    </StatusMessage>
                  ) : null}
                  {deploymentRevision?.lifecycleState === 'deployment_failed' ? (
                    <StatusMessage intent="error">
                      Deployment failed. Review the health diagnostics before retrying.
                    </StatusMessage>
                  ) : null}
                </InfoPanel>
                <InfoPanel title="Health">
                  {deploymentRevision ? (
                    <>
                      <Body1 block>Status: {deploymentRevision.health.status}</Body1>
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
          </SectionCard>
        </>
      ) : null}
    </div>
  );
}
