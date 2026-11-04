import { useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import {
  Body1,
  Button,
  Field,
  Input,
  Select,
  Table,
  TableBody,
  TableCell,
  TableHeader,
  TableHeaderCell,
  TableRow,
  makeStyles,
  tokens,
} from '@fluentui/react-components';
import EnvironmentPicker from '../components/EnvironmentPicker';
import { ApiError } from '../services/apiClient';
import {
  getEnvironment,
  previewTeardown,
  teardownEnvironment,
} from '../services/environmentsApi';
import type {
  DemoEnvironment,
  TeardownPreviewResponse,
  TeardownResult,
} from '../services/types';
import {
  DataList,
  EmptyState,
  InfoGrid,
  InfoPanel,
  PageHeader,
  RouterButton,
  RouterLink,
  SectionCard,
  StatusBadge,
  StatusMessage,
  formatStateLabel,
  statusTone,
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
  dangerButton: {
    backgroundColor: tokens.colorPaletteRedBackground3,
    color: tokens.colorNeutralForegroundOnBrand,
  },
});

function consequenceTone(value: 'remove' | 'retain' | 'export') {
  switch (value) {
    case 'remove':
      return 'warning';
    case 'export':
      return 'info';
    default:
      return 'neutral';
  }
}

function outcomeTone(value: 'removed' | 'retained' | 'failed') {
  if (value === 'failed') {
    return statusTone('failed');
  }

  return value === 'removed' ? 'success' : 'neutral';
}

function getTeardownErrorMessage(error: unknown) {
  if (error instanceof ApiError) {
    return error.message;
  }

  return error instanceof Error ? error.message : 'Teardown request failed.';
}

export default function TeardownPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [environmentId, setEnvironmentId] = useState(searchParams.get('environmentId') ?? '');
  const [environment, setEnvironment] = useState<DemoEnvironment>();
  const [environmentLoading, setEnvironmentLoading] = useState(false);
  const [environmentError, setEnvironmentError] = useState<string>();
  const [preservationMode, setPreservationMode] = useState<'retain' | 'export'>('retain');
  const [preview, setPreview] = useState<TeardownPreviewResponse>();
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewError, setPreviewError] = useState<string>();
  const [confirmationText, setConfirmationText] = useState('');
  const [executing, setExecuting] = useState(false);
  const [teardownError, setTeardownError] = useState<string>();
  const [teardownResult, setTeardownResult] = useState<TeardownResult>();

  const confirmationTargets = useMemo(
    () => [environment?.environmentId, environment?.name].filter(Boolean) as string[],
    [environment?.environmentId, environment?.name],
  );
  const confirmationMatched = confirmationTargets.some(
    (candidate) => candidate === confirmationText.trim(),
  );
  const canExecute = Boolean(
    environment?.environmentId && preview?.previewToken && confirmationMatched && !executing,
  );

  async function handleLoadEnvironment(nextEnvironmentId: string = environmentId) {
    if (!nextEnvironmentId.trim()) {
      setEnvironmentError('Select an environment to preview its teardown impact.');
      return;
    }

    setEnvironmentLoading(true);
    setEnvironmentError(undefined);

    try {
      const nextEnvironment = await getEnvironment(nextEnvironmentId.trim());
      setEnvironment(nextEnvironment);
      setEnvironmentId(nextEnvironment.environmentId);
      setSearchParams({ environmentId: nextEnvironment.environmentId });
      setPreview(undefined);
      setPreviewError(undefined);
      setConfirmationText('');
      setTeardownResult(undefined);
      setTeardownError(undefined);
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

  async function handlePreview() {
    if (!environment?.environmentId) {
      return;
    }

    setPreviewLoading(true);
    setPreviewError(undefined);
    setTeardownResult(undefined);
    setTeardownError(undefined);
    setConfirmationText('');

    try {
      const response = await previewTeardown(environment.environmentId, { preservationMode });
      setPreview(response);
    } catch (error) {
      setPreviewError(getTeardownErrorMessage(error));
      setPreview(undefined);
    } finally {
      setPreviewLoading(false);
    }
  }

  async function handleTeardown() {
    if (!environment?.environmentId || !preview?.previewToken) {
      return;
    }

    setExecuting(true);
    setTeardownError(undefined);

    try {
      const response = await teardownEnvironment(environment.environmentId, {
        previewToken: preview.previewToken,
        confirmationText: confirmationText.trim(),
        preservationMode,
      });

      setTeardownResult(response);
      const refreshedEnvironment = await getEnvironment(environment.environmentId);
      setEnvironment(refreshedEnvironment);
    } catch (error) {
      setTeardownError(getTeardownErrorMessage(error));
      setTeardownResult(undefined);
    } finally {
      setExecuting(false);
    }
  }

  const styles = useStyles();

  return (
    <div className={styles.stack}>
      <PageHeader
        eyebrow="Manage"
        title="Tear down an environment"
        description="Preview exactly what will be removed or retained, then confirm the teardown with an explicit typed acknowledgment before the environment is dismantled."
      />

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
            <InfoPanel title="Current state">
              <DataList
                items={[
                  { label: 'Environment id', value: environment.environmentId },
                  { label: 'Profile', value: environment.profileId },
                  { label: 'Region', value: environment.region },
                  {
                    label: 'Lifecycle',
                    value: (
                      <StatusBadge tone={statusTone(environment.state)}>
                        {formatStateLabel(environment.state)}
                      </StatusBadge>
                    ),
                  },
                  {
                    label: 'Active deployment revision',
                    value:
                      environment.activeDeploymentRevisionId ?? environment.activeRevisionId ?? 'None',
                  },
                ]}
              />
            </InfoPanel>
            <InfoPanel title="Before you continue">
              <Body1>
                The preview token ties your confirmation to a specific environment snapshot. If you
                change the preservation mode or environment, generate a fresh preview before you tear
                anything down.
              </Body1>
            </InfoPanel>
          </InfoGrid>
        ) : (
          <EmptyState title="Choose an environment to inspect">
            Select the environment you want to tear down, then generate a resource impact preview.
          </EmptyState>
        )}
      </SectionCard>

      <SectionCard
        title="2. Preview"
        description="Choose how teardown should treat retained artifacts, then inspect the exact resources and consequences before you confirm anything destructive."
      >
        {!environment ? (
          <EmptyState title="Load an environment first">
            The teardown preview becomes available after you select an environment.
          </EmptyState>
        ) : (
          <>
            <div className={styles.formGrid}>
              <Field label="Preservation mode">
                <Select
                  aria-label="Preservation mode"
                  value={preservationMode}
                  onChange={(event) => {
                    const nextMode = event.target.value as 'retain' | 'export';
                    setPreservationMode(nextMode);
                    setPreview(undefined);
                    setTeardownResult(undefined);
                    setConfirmationText('');
                    setPreviewError(undefined);
                    setTeardownError(undefined);
                  }}
                >
                  <option value="retain">Retain referenced artifacts</option>
                  <option value="export">Export retained artifacts</option>
                </Select>
              </Field>
            </div>

            {previewError ? <StatusMessage intent="error">{previewError}</StatusMessage> : null}
            <div className={styles.actions}>
              <Button appearance="primary" onClick={() => void handlePreview()} disabled={previewLoading}>
                {previewLoading ? 'Generating preview…' : 'Preview teardown'}
              </Button>
            </div>

            {preview ? (
              <>
                <Table aria-label="Teardown preview resources" size="small">
                  <TableHeader>
                    <TableRow>
                      <TableHeaderCell>Id</TableHeaderCell>
                      <TableHeaderCell>Name</TableHeaderCell>
                      <TableHeaderCell>Type</TableHeaderCell>
                      <TableHeaderCell>Consequence</TableHeaderCell>
                      <TableHeaderCell>Notes</TableHeaderCell>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {preview.resources.map((resource) => (
                      <TableRow key={resource.id}>
                        <TableCell>{resource.id}</TableCell>
                        <TableCell>{resource.name}</TableCell>
                        <TableCell>{resource.type}</TableCell>
                        <TableCell>
                          <StatusBadge tone={consequenceTone(resource.consequence)}>
                            {formatStateLabel(resource.consequence)}
                          </StatusBadge>
                        </TableCell>
                        <TableCell>{resource.notes?.join('; ') ?? '—'}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>

                <InfoPanel title="Preview consequences">
                  <ul className={styles.list}>
                    {preview.consequences.map((consequence) => (
                      <li key={consequence}>
                        <Body1>{consequence}</Body1>
                      </li>
                    ))}
                  </ul>
                </InfoPanel>
              </>
            ) : (
              <EmptyState title="No preview generated yet">
                Generate a preview to see the exact resource list, preview token, and teardown
                consequences before the destructive confirmation step is enabled.
              </EmptyState>
            )}
          </>
        )}
      </SectionCard>

      <SectionCard
        title="3. Confirm and execute"
        description="Type the environment id or name exactly as shown, then run the teardown using the preview token from the previous step."
      >
        {!environment ? (
          <EmptyState title="Load an environment first">
            The confirmation step appears only after an environment is selected and previewed.
          </EmptyState>
        ) : !preview ? (
          <EmptyState title="Preview required first">
            Generate a teardown preview before you can confirm or execute the destructive step.
          </EmptyState>
        ) : (
          <>
            <InfoGrid>
              <InfoPanel title="Confirmation target">
                <DataList
                  items={[
                    { label: 'Preview token', value: preview.previewToken },
                    {
                      label: 'Accepted confirmation text',
                      value: confirmationTargets.join(' or '),
                    },
                    { label: 'Preservation mode', value: formatStateLabel(preservationMode) },
                  ]}
                />
              </InfoPanel>
            </InfoGrid>

            <Field
              label="Type the environment id or name to confirm"
              hint="The destructive button stays disabled until this text matches exactly."
            >
              <Input
                aria-label="Teardown confirmation text"
                value={confirmationText}
                onChange={(event) => setConfirmationText(event.target.value)}
                placeholder={confirmationTargets[0] ?? 'environment id'}
              />
            </Field>

            {!confirmationMatched ? (
              <StatusMessage intent="warning">
                Enter one of the displayed confirmation targets exactly to unlock the teardown
                action.
              </StatusMessage>
            ) : null}
            {teardownError ? <StatusMessage intent="error">{teardownError}</StatusMessage> : null}

            <div className={styles.actions}>
              <Button
                appearance="primary"
                className={styles.dangerButton}
                onClick={() => void handleTeardown()}
                disabled={!canExecute}
              >
                {executing ? 'Tearing down…' : 'Tear down environment'}
              </Button>
            </div>

            {teardownResult ? (
              <>
                <InfoGrid>
                  <InfoPanel title="Teardown result">
                    <DataList
                      items={[
                        { label: 'Operation id', value: teardownResult.operationId },
                        { label: 'Phase', value: formatStateLabel(teardownResult.phase) },
                        {
                          label: 'Status',
                          value: (
                            <StatusBadge tone={statusTone(teardownResult.status)}>
                              {formatStateLabel(teardownResult.status)}
                            </StatusBadge>
                          ),
                        },
                      ]}
                    />
                    {teardownResult.status === 'completed' ? (
                      <StatusMessage intent="success">
                        Teardown completed. Retained reports remain accessible from Experiment
                        History.
                      </StatusMessage>
                    ) : null}
                  </InfoPanel>
                </InfoGrid>

                <Table aria-label="Teardown resource outcomes" size="small">
                  <TableHeader>
                    <TableRow>
                      <TableHeaderCell>Id</TableHeaderCell>
                      <TableHeaderCell>Name</TableHeaderCell>
                      <TableHeaderCell>Outcome</TableHeaderCell>
                      <TableHeaderCell>Detail</TableHeaderCell>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {teardownResult.resourceOutcomes.map((resource) => (
                      <TableRow key={resource.id}>
                        <TableCell>{resource.id}</TableCell>
                        <TableCell>{resource.name}</TableCell>
                        <TableCell>
                          <StatusBadge tone={outcomeTone(resource.outcome)}>
                            {formatStateLabel(resource.outcome)}
                          </StatusBadge>
                        </TableCell>
                        <TableCell>{resource.detail ?? '—'}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>

                {environment.environmentId ? (
                  <div className={styles.actions}>
                    <RouterButton
                      appearance="primary"
                      to={`/history?environmentId=${encodeURIComponent(environment.environmentId)}`}
                    >
                      Next: open Experiment History
                    </RouterButton>
                  </div>
                ) : null}
              </>
            ) : null}
          </>
        )}
      </SectionCard>
    </div>
  );
}
