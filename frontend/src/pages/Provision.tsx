import { useEffect, useMemo, useRef, useState } from 'react';
import {
  Body1,
  Button,
  Caption1,
  Field,
  Input,
  Select,
  Switch,
  Table,
  TableBody,
  TableCell,
  TableHeader,
  TableHeaderCell,
  TableRow,
  makeStyles,
  tokens,
} from '@fluentui/react-components';
import { listCatalog, listProfiles } from '../services/catalogApi';
import {
  getEnvironment,
  isEnvironmentSettled,
  previewEnvironment,
  provisionEnvironment,
} from '../services/environmentsApi';
import type {
  AcceptedOperation,
  CloudDeploymentProfile,
  DemoEnvironment,
  DemoEnvironmentResource,
  EnvironmentPreviewResponse,
  ModelCatalogEntry,
} from '../services/types';
import {
  DataList,
  EmptyState,
  InfoGrid,
  InfoPanel,
  LoadingState,
  PageHeader,
  RouterButton,
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
  hint: {
    color: tokens.colorNeutralForeground3,
  },
  list: {
    margin: 0,
    paddingLeft: tokens.spacingHorizontalL,
    display: 'flex',
    flexDirection: 'column',
    gap: tokens.spacingVerticalXXS,
  },
  progressLog: {
    margin: 0,
    paddingLeft: tokens.spacingHorizontalL,
    display: 'flex',
    flexDirection: 'column',
    gap: tokens.spacingVerticalXS,
  },
});

type ProfileInputValue = string | number | boolean;

type ProgressEntry = {
  at: string;
  message: string;
};

const POLL_INTERVAL_MS = 1500;
const PROVISIONING_STORAGE_KEY = 'llmDemo.activeProvisioning';

type StoredProvisioningState = {
  operation: AcceptedOperation;
  progressEntries: ProgressEntry[];
  selectedProfileId: string;
  selectedModelId: string;
  environmentName: string;
  selectedRegion: string;
  startedAt: number;
};

function readStoredProvisioning(): StoredProvisioningState | undefined {
  try {
    const raw = window.localStorage.getItem(PROVISIONING_STORAGE_KEY);
    if (!raw) {
      return undefined;
    }

    return JSON.parse(raw) as StoredProvisioningState;
  } catch {
    return undefined;
  }
}

function writeStoredProvisioning(state: StoredProvisioningState | undefined) {
  try {
    if (!state) {
      window.localStorage.removeItem(PROVISIONING_STORAGE_KEY);
      return;
    }

    window.localStorage.setItem(PROVISIONING_STORAGE_KEY, JSON.stringify(state));
  } catch {
    // localStorage may be unavailable (e.g. private browsing); losing resume support is
    // acceptable in that case, but provisioning itself should continue to work.
  }
}

function formatTimestamp(value?: string) {
  if (!value) {
    return 'n/a';
  }

  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString();
}

function getResourceSummary(resources: DemoEnvironmentResource[]) {
  const total = resources.length;

  if (total === 0) {
    return 'Waiting for provider resource details';
  }

  const readyCount = resources.filter((resource) =>
    ['ready', 'running', 'succeeded', 'active'].includes(resource.state.toLowerCase()),
  ).length;

  return `${readyCount}/${total} resources reporting ready/running`;
}

function getInitialInputs(profile?: CloudDeploymentProfile) {
  return (profile?.configurableInputs ?? []).reduce<Record<string, ProfileInputValue>>(
    (accumulator, input) => {
      if (input.defaultValue !== undefined) {
        accumulator[input.name] = input.defaultValue;
      }

      return accumulator;
    },
    {},
  );
}

function getInputValue(
  input: CloudDeploymentProfile['configurableInputs'][number],
  rawValue: string,
): ProfileInputValue {
  if (input.type === 'number') {
    return rawValue === '' ? 0 : Number(rawValue);
  }

  return rawValue;
}

function isLocalProfile(profile?: CloudDeploymentProfile) {
  return profile?.provider === 'local';
}

export default function ProvisionPage() {
  const initialStoredProvisioning = useMemo(() => readStoredProvisioning(), []);
  const [profiles, setProfiles] = useState<CloudDeploymentProfile[]>([]);
  const [catalogEntries, setCatalogEntries] = useState<ModelCatalogEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string>();
  const [selectedProfileId, setSelectedProfileId] = useState(
    initialStoredProvisioning?.selectedProfileId ?? '',
  );
  const [selectedModelId, setSelectedModelId] = useState(
    initialStoredProvisioning?.selectedModelId ?? '',
  );
  const [environmentName, setEnvironmentName] = useState(
    initialStoredProvisioning?.environmentName ?? '',
  );
  const [selectedRegion, setSelectedRegion] = useState(
    initialStoredProvisioning?.selectedRegion ?? '',
  );
  const [profileInputs, setProfileInputs] = useState<Record<string, ProfileInputValue>>({});
  const [preview, setPreview] = useState<EnvironmentPreviewResponse>();
  const [previewError, setPreviewError] = useState<string>();
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewedRegion, setPreviewedRegion] = useState('');
  const [operation, setOperation] = useState<AcceptedOperation | undefined>(
    initialStoredProvisioning?.operation,
  );
  const [provisionError, setProvisionError] = useState<string>();
  const [provisioning, setProvisioning] = useState(Boolean(initialStoredProvisioning));
  const [environment, setEnvironment] = useState<DemoEnvironment>();
  const [progressEntries, setProgressEntries] = useState<ProgressEntry[]>(
    initialStoredProvisioning?.progressEntries ?? [],
  );
  const [provisioningStartedAt, setProvisioningStartedAt] = useState<number | undefined>(
    initialStoredProvisioning?.startedAt,
  );
  const [elapsedSeconds, setElapsedSeconds] = useState(0);
  const skipNextProfileReset = useRef(Boolean(initialStoredProvisioning));

  const selectedProfile = useMemo(
    () => profiles.find((profile) => profile.id === selectedProfileId),
    [profiles, selectedProfileId],
  );

  const compatibleModels = useMemo(
    () =>
      catalogEntries.filter((entry) =>
        selectedProfileId ? entry.compatibleProfileIds.includes(selectedProfileId) : false,
      ),
    [catalogEntries, selectedProfileId],
  );

  const selectedModel = useMemo(
    () => compatibleModels.find((entry) => entry.id === selectedModelId),
    [compatibleModels, selectedModelId],
  );

  const previewIsCurrent = Boolean(preview && selectedRegion && selectedRegion === previewedRegion);
  const canPreview = Boolean(selectedProfileId && selectedModelId);
  const canConfirm = Boolean(previewIsCurrent && selectedRegion && !provisioning);

  useEffect(() => {
    let cancelled = false;

    async function loadData() {
      try {
        const [profilesResponse, catalogResponse] = await Promise.all([
          listProfiles(),
          listCatalog(),
        ]);

        if (cancelled) {
          return;
        }

        setProfiles(profilesResponse.profiles);
        setCatalogEntries(catalogResponse.entries);
      } catch (error) {
        if (!cancelled) {
          setLoadError(error instanceof Error ? error.message : 'Failed to load provisioning data.');
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    }

    void loadData();

    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (skipNextProfileReset.current) {
      skipNextProfileReset.current = false;
      return;
    }

    setSelectedModelId('');
    setSelectedRegion('');
    setPreview(undefined);
    setPreviewError(undefined);
    setPreviewedRegion('');
    setOperation(undefined);
    setProvisionError(undefined);
    setEnvironment(undefined);
    setProgressEntries([]);
    setElapsedSeconds(0);
    setProvisioningStartedAt(undefined);
    setProvisioning(false);
    writeStoredProvisioning(undefined);
    setProfileInputs(getInitialInputs(selectedProfile));
  }, [selectedProfileId, selectedProfile]);

  useEffect(() => {
    if (!operation?.environmentId) {
      return;
    }

    const environmentId = operation.environmentId;
    let active = true;
    let timeoutId: number | undefined;

    const poll = async () => {
      try {
        const nextEnvironment = await getEnvironment(environmentId);

        if (!active) {
          return;
        }

        setEnvironment(nextEnvironment);
        setProgressEntries((existing) => {
          const nextMessage = `${formatStateLabel(nextEnvironment.state)} — ${getResourceSummary(
            nextEnvironment.resources,
          )}`;
          const lastMessage = existing.at(-1)?.message;

          if (lastMessage === nextMessage) {
            return existing;
          }

          return [...existing, { at: new Date().toISOString(), message: nextMessage }];
        });

        if (!isEnvironmentSettled(nextEnvironment.state)) {
          timeoutId = window.setTimeout(poll, POLL_INTERVAL_MS);
        } else {
          setProvisioning(false);
          writeStoredProvisioning(undefined);
        }
      } catch (error) {
        if (!active) {
          return;
        }

        setProvisionError(
          error instanceof Error ? error.message : 'Polling the environment state failed.',
        );
        setProvisioning(false);
      }
    };

    void poll();

    return () => {
      active = false;
      if (timeoutId !== undefined) {
        window.clearTimeout(timeoutId);
      }
    };
  }, [operation?.environmentId]);

  useEffect(() => {
    if (!provisioning || !provisioningStartedAt) {
      return;
    }

    const update = () =>
      setElapsedSeconds(Math.floor((Date.now() - provisioningStartedAt) / 1000));

    update();
    const intervalId = window.setInterval(update, 1000);

    return () => {
      window.clearInterval(intervalId);
    };
  }, [provisioning, provisioningStartedAt]);

  useEffect(() => {
    if (!operation?.environmentId) {
      return;
    }

    writeStoredProvisioning({
      operation,
      progressEntries,
      selectedProfileId,
      selectedModelId,
      environmentName,
      selectedRegion,
      startedAt: provisioningStartedAt ?? Date.now(),
    });
  }, [
    operation,
    progressEntries,
    selectedProfileId,
    selectedModelId,
    environmentName,
    selectedRegion,
    provisioningStartedAt,
  ]);

  async function handlePreview() {
    if (!selectedProfileId) {
      return;
    }

    setPreviewLoading(true);
    setPreviewError(undefined);

    try {
      const requestedRegion =
        selectedRegion && selectedProfile?.regions.includes(selectedRegion)
          ? selectedRegion
          : undefined;

      const response = await previewEnvironment({
        profileId: selectedProfileId,
        regionOverride: requestedRegion,
      });

      const resolvedRegion = requestedRegion ?? response.recommendedRegion;

      setPreview(response);
      setSelectedRegion(resolvedRegion);
      setPreviewedRegion(resolvedRegion);
    } catch (error) {
      setPreviewError(error instanceof Error ? error.message : 'Preview failed.');
    } finally {
      setPreviewLoading(false);
    }
  }

  async function handleProvision() {
    if (!selectedProfileId || !selectedRegion) {
      return;
    }

    setProvisionError(undefined);
    setProvisioning(true);

    try {
      const response = await provisionEnvironment({
        profileId: selectedProfileId,
        region: selectedRegion,
        name: environmentName.trim() || undefined,
        inputs: Object.keys(profileInputs).length > 0 ? profileInputs : undefined,
      });

      if (!response.environmentId) {
        throw new Error('Provisioning response did not include an environment id to poll.');
      }

      setOperation(response);
      setEnvironment(undefined);
      setElapsedSeconds(0);
      setProvisioningStartedAt(Date.now());
      setProgressEntries([
        {
          at: new Date().toISOString(),
          message: `${formatStateLabel(response.phase)} — ${
            response.message ?? 'Provisioning request accepted.'
          }`,
        },
      ]);
    } catch (error) {
      setProvisionError(error instanceof Error ? error.message : 'Provisioning failed to start.');
      setProvisioning(false);
    }
  }

  const styles = useStyles();

  return (
    <div className={styles.stack}>
      <PageHeader
        eyebrow="Setup"
        title="Provision a demo environment"
        description="Pick an Azure or local deployment profile and a compatible model, confirm the region preview, then watch the environment settle in real time."
      />

      {loading ? <LoadingState label="Loading profiles and catalog…" /> : null}
      {loadError ? (
        <StatusMessage intent="error" title="Couldn't load provisioning data">
          {loadError}
        </StatusMessage>
      ) : null}

      {!loading && !loadError ? (
        <>
          <SectionCard
            title="1. Choose a profile and model"
            description="The model list narrows to entries compatible with the selected profile."
          >
            <div className={styles.formGrid}>
              <Field label="Cloud deployment profile">
                <Select
                  aria-label="Cloud deployment profile"
                  value={selectedProfileId}
                  onChange={(event) => setSelectedProfileId(event.target.value)}
                >
                  <option value="">Select a profile</option>
                  {profiles.map((profile) => (
                    <option key={profile.id} value={profile.id}>
                      {profile.name} ({profile.provider}, {profile.sizeClass})
                    </option>
                  ))}
                </Select>
              </Field>

              <Field label="Model catalog entry">
                <Select
                  aria-label="Model catalog entry"
                  disabled={!selectedProfileId}
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

              <Field label="Environment name (optional)">
                <Input
                  aria-label="Environment name"
                  value={environmentName}
                  onChange={(event) => setEnvironmentName(event.target.value)}
                  placeholder="azure-llm-demo"
                />
              </Field>

              <Field label={isLocalProfile(selectedProfile) ? 'Runtime location' : 'Provisioning region'}>
                <Select
                  aria-label={isLocalProfile(selectedProfile) ? 'Runtime location' : 'Provisioning region'}
                  disabled={!selectedProfile}
                  value={selectedRegion}
                  onChange={(event) => setSelectedRegion(event.target.value)}
                >
                  <option value="">
                    {isLocalProfile(selectedProfile)
                      ? 'Use local runtime recommendation'
                      : 'Use preview recommendation'}
                  </option>
                  {selectedProfile?.regions.map((region) => (
                    <option key={region} value={region}>
                      {region}
                    </option>
                  ))}
                </Select>
              </Field>
            </div>

            {selectedProfile ? (
              <InfoGrid>
                <InfoPanel title="Profile details">
                  <DataList
                    items={[
                      { label: 'Expected model class', value: selectedProfile.expectedModelClass },
                      {
                        label: 'Eligible regions',
                        value: selectedProfile.regions.length
                          ? selectedProfile.regions.join(', ')
                          : 'Not applicable for local runtime',
                      },
                    ]}
                  />
                  <Body1>{selectedProfile.description}</Body1>
                  <ul className={styles.list}>
                    {selectedProfile.resourceAssumptions.map((item) => (
                      <li key={item}>
                        <Body1>{item}</Body1>
                      </li>
                    ))}
                  </ul>
                </InfoPanel>

                <InfoPanel title="Compatible model context">
                  {selectedModel ? (
                    <>
                      <Body1 block>
                        <strong>{selectedModel.family}</strong> — {selectedModel.huggingFaceRepo} @{' '}
                        {selectedModel.checkpoint}
                      </Body1>
                      <Body1 block>License: {selectedModel.license}</Body1>
                      <Body1 block>
                        Access: {selectedModel.gated ? 'Gated Hugging Face access required' : 'Open'}
                      </Body1>
                      {selectedModel.demonstrationValue ? (
                        <Body1 block>{selectedModel.demonstrationValue}</Body1>
                      ) : null}
                    </>
                  ) : (
                    <Body1 className={styles.hint}>Select a model to review the curated catalog entry.</Body1>
                  )}
                </InfoPanel>
              </InfoGrid>
            ) : null}

            {isLocalProfile(selectedProfile) ? (
              <StatusMessage intent="info">
                Local (Ollama) provisioning does not create cloud resources. The runtime becomes
                ready as soon as the configured Ollama endpoint responds.
              </StatusMessage>
            ) : null}

            {selectedProfile?.configurableInputs.length ? (
              <InfoPanel title="Profile inputs">
                <div className={styles.formGrid}>
                  {selectedProfile.configurableInputs.map((input) => (
                    <Field label={input.name} hint={input.description} key={input.name}>
                      {input.type === 'boolean' ? (
                        <Switch
                          aria-label={input.name}
                          checked={Boolean(profileInputs[input.name])}
                          onChange={(event) =>
                            setProfileInputs((existing) => ({
                              ...existing,
                              [input.name]: event.target.checked,
                            }))
                          }
                        />
                      ) : input.type === 'enum' ? (
                        <Select
                          aria-label={input.name}
                          value={String(profileInputs[input.name] ?? input.defaultValue ?? '')}
                          onChange={(event) =>
                            setProfileInputs((existing) => ({
                              ...existing,
                              [input.name]: event.target.value,
                            }))
                          }
                        >
                          <option value="">Select {input.name}</option>
                          {input.options?.map((option) => (
                            <option key={option} value={option}>
                              {option}
                            </option>
                          ))}
                        </Select>
                      ) : (
                        <Input
                          aria-label={input.name}
                          type={input.type === 'number' ? 'number' : 'text'}
                          value={String(profileInputs[input.name] ?? input.defaultValue ?? '')}
                          onChange={(event) =>
                            setProfileInputs((existing) => ({
                              ...existing,
                              [input.name]: getInputValue(input, event.target.value),
                            }))
                          }
                        />
                      )}
                    </Field>
                  ))}
                </div>
              </InfoPanel>
            ) : null}

            <div>
              <Button
                appearance="primary"
                disabled={!canPreview || previewLoading}
                onClick={handlePreview}
              >
                {previewLoading ? 'Previewing…' : 'Preview region recommendation'}
              </Button>
            </div>
          </SectionCard>

          {preview ? (
            <SectionCard title="2. Preview recommendation">
              <StatusMessage intent="info">
                {isLocalProfile(selectedProfile) ? 'Recommended runtime' : 'Recommended region'}:{' '}
                <strong>{preview.recommendedRegion}</strong>
                {selectedRegion && selectedRegion !== preview.recommendedRegion
                  ? ` — you are previewing an override for ${selectedRegion}.`
                  : ''}
              </StatusMessage>
              <Caption1 className={styles.hint}>Preview request: {preview.requestId}</Caption1>
              {preview.advisoryMessage ? <Body1>{preview.advisoryMessage}</Body1> : null}
              {!previewIsCurrent ? (
                <StatusMessage intent="warning">
                  The selected region changed after the last preview. Refresh the preview before
                  confirming provisioning so quota and capacity are revalidated.
                </StatusMessage>
              ) : null}
              {previewError ? <StatusMessage intent="error">{previewError}</StatusMessage> : null}

              <Table aria-label="Region assessments" size="small">
                <TableHeader>
                  <TableRow>
                    <TableHeaderCell>Region</TableHeaderCell>
                    <TableHeaderCell>Quota</TableHeaderCell>
                    <TableHeaderCell>Capacity</TableHeaderCell>
                    <TableHeaderCell>Compatibility</TableHeaderCell>
                    <TableHeaderCell>Checked at</TableHeaderCell>
                    <TableHeaderCell>Evidence</TableHeaderCell>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {preview.assessments.map((assessment) => (
                    <TableRow key={assessment.region}>
                      <TableCell>{assessment.region}</TableCell>
                      <TableCell>{assessment.quotaStatus}</TableCell>
                      <TableCell>{assessment.capacityStatus}</TableCell>
                      <TableCell>{assessment.compatibilityStatus}</TableCell>
                      <TableCell>{formatTimestamp(assessment.checkedAt)}</TableCell>
                      <TableCell>
                        <ul className={styles.list}>
                          {assessment.evidence.map((item) => (
                            <li key={item}>
                              <Caption1>{item}</Caption1>
                            </li>
                          ))}
                          {assessment.uncertainty ? (
                            <li>
                              <Caption1>
                                <strong>Uncertainty:</strong> {assessment.uncertainty}
                              </Caption1>
                            </li>
                          ) : null}
                        </ul>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </SectionCard>
          ) : null}

          {previewError && !preview ? <StatusMessage intent="error">{previewError}</StatusMessage> : null}

          {preview ? (
            <SectionCard title="3. Confirm provisioning">
              <InfoGrid>
                <InfoPanel title="Selected inputs">
                  <DataList
                    items={[
                      { label: 'Profile', value: selectedProfile?.name },
                      { label: 'Model', value: selectedModel?.huggingFaceRepo },
                      { label: 'Region', value: selectedRegion || preview.recommendedRegion },
                    ]}
                  />
                </InfoPanel>

                <InfoPanel title="Capacity and fallback context">
                  <Body1>
                    {isLocalProfile(selectedProfile)
                      ? 'The preview confirms local runtime assumptions and records readiness guidance before provisioning.'
                      : 'The preview preserves recommendation evidence and uncertainty so presenters can explain why a fallback region may be necessary before provisioning.'}
                  </Body1>
                  <ul className={styles.list}>
                    {preview.assessments
                      .filter((assessment) => assessment.region !== preview.recommendedRegion)
                      .map((assessment) => (
                        <li key={assessment.region}>
                          <Body1>
                            {assessment.region}: {assessment.capacityStatus}, quota{' '}
                            {assessment.quotaStatus}
                          </Body1>
                        </li>
                      ))}
                  </ul>
                </InfoPanel>
              </InfoGrid>

              {provisionError ? <StatusMessage intent="error">{provisionError}</StatusMessage> : null}
              <div>
                <Button appearance="primary" disabled={!canConfirm} onClick={handleProvision}>
                  {provisioning ? 'Provisioning…' : 'Confirm provisioning'}
                </Button>
              </div>
            </SectionCard>
          ) : null}

          {operation ? (
            <SectionCard title="4. Provisioning progress">
              <InfoGrid>
                <InfoPanel>
                  <DataList
                    items={[
                      { label: 'Operation id', value: operation.operationId },
                      { label: 'Current phase', value: formatStateLabel(environment?.state ?? operation.phase) },
                      { label: 'Elapsed', value: `${elapsedSeconds}s` },
                      { label: 'Environment', value: operation.environmentId },
                    ]}
                  />
                  <Body1>
                    {environment
                      ? `Environment is ${formatStateLabel(environment.state).toLowerCase()}.`
                      : 'Waiting for the first environment status poll.'}
                  </Body1>
                  {environment?.state === 'ready' ? (
                    <StatusMessage intent="success">
                      Environment ready. You can inspect the provisioned resources in detail.
                    </StatusMessage>
                  ) : null}
                  {environment?.state === 'provisioning_failed' ? (
                    <StatusMessage intent="error">
                      Provisioning ended in a terminal failure state.
                    </StatusMessage>
                  ) : null}
                </InfoPanel>

                <InfoPanel title="Resource state">
                  {environment?.resources.length ? (
                    <ul className={styles.list}>
                      {environment.resources.map((resource) => (
                        <li key={`${resource.type}-${resource.name}`}>
                          <Body1>
                            <strong>{resource.name}</strong> ({resource.type}) — {resource.state}
                            {resource.summary ? `: ${resource.summary}` : ''}
                          </Body1>
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <EmptyState title="No provider resources reported yet">
                      Resource details appear here once the provider starts reporting status.
                    </EmptyState>
                  )}
                </InfoPanel>
              </InfoGrid>

              <InfoPanel title="Progress log">
                <ol className={styles.progressLog}>
                  {progressEntries.map((entry, index) => (
                    <li key={`${entry.at}-${index}`}>
                      <Caption1>{formatTimestamp(entry.at)}</Caption1> — <Body1 as="span">{entry.message}</Body1>
                    </li>
                  ))}
                </ol>
              </InfoPanel>

              {operation.environmentId ? (
                <div>
                  <RouterButton appearance="primary" to={`/environments/${operation.environmentId}`}>
                    Open environment detail
                  </RouterButton>
                </div>
              ) : null}
            </SectionCard>
          ) : null}
        </>
      ) : null}
    </div>
  );
}
