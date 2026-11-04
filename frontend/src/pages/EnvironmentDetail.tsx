import { useEffect, useMemo, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import {
  Body1,
  Table,
  TableBody,
  TableCell,
  TableHeader,
  TableHeaderCell,
  TableRow,
  Title3,
  makeStyles,
  tokens,
} from '@fluentui/react-components';
import EnvironmentPicker from '../components/EnvironmentPicker';
import { listProfiles } from '../services/catalogApi';
import { getEnvironment, isEnvironmentSettled } from '../services/environmentsApi';
import type { CloudDeploymentProfile, DemoEnvironment } from '../services/types';
import {
  DataList,
  EmptyState,
  InfoGrid,
  InfoPanel,
  LoadingState,
  PageHeader,
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
  list: {
    margin: 0,
    paddingLeft: tokens.spacingHorizontalL,
    display: 'flex',
    flexDirection: 'column',
    gap: tokens.spacingVerticalXXS,
  },
});

const POLL_INTERVAL_MS = 1500;

function formatTimestamp(value?: string) {
  if (!value) {
    return 'n/a';
  }

  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString();
}

export default function EnvironmentDetailPage() {
  const { environmentId = '' } = useParams();
  const navigate = useNavigate();
  const styles = useStyles();
  const [environment, setEnvironment] = useState<DemoEnvironment>();
  const [profiles, setProfiles] = useState<CloudDeploymentProfile[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string>();
  const activeDeploymentRevisionId =
    environment?.activeDeploymentRevisionId ?? environment?.activeRevisionId;

  const profile = useMemo(
    () => profiles.find((candidate) => candidate.id === environment?.profileId),
    [environment?.profileId, profiles],
  );

  useEffect(() => {
    let active = true;
    let timeoutId: number | undefined;

    async function load() {
      try {
        const [environmentResponse, profilesResponse] = await Promise.all([
          getEnvironment(environmentId),
          listProfiles(),
        ]);

        if (!active) {
          return;
        }

        setEnvironment(environmentResponse);
        setProfiles(profilesResponse.profiles);
        setError(undefined);

        if (!isEnvironmentSettled(environmentResponse.state)) {
          timeoutId = window.setTimeout(() => {
            void load();
          }, POLL_INTERVAL_MS);
        }
      } catch (nextError) {
        if (active) {
          setError(
            nextError instanceof Error ? nextError.message : 'Unable to load environment details.',
          );
        }
      } finally {
        if (active) {
          setLoading(false);
        }
      }
    }

    if (environmentId) {
      void load();
    } else {
      setEnvironment(undefined);
      setLoading(false);
      setError(undefined);
    }

    return () => {
      active = false;
      if (timeoutId !== undefined) {
        window.clearTimeout(timeoutId);
      }
    };
  }, [environmentId]);

  if (!environmentId) {
    return (
      <div className={styles.stack}>
        <PageHeader
          title="Environment detail"
          description="Select an environment to inspect its provisioned profile, current lifecycle state, active deployment revision, and capacity context."
        />

        <SectionCard title="Select an environment">
          <div className={styles.formGrid}>
            <EnvironmentPicker
              value=""
              onSelect={(nextEnvironmentId) => {
                if (nextEnvironmentId) {
                  navigate(`/environments/${nextEnvironmentId}`);
                }
              }}
            />
          </div>
        </SectionCard>
      </div>
    );
  }

  return (
    <div className={styles.stack}>
      <PageHeader
        title="Environment detail"
        description="Inspect the provisioned profile, current lifecycle state, active deployment revision, and the capacity context behind the chosen region."
      />

      {loading ? <LoadingState label="Loading environment details…" /> : null}
      {error ? <StatusMessage intent="error">{error}</StatusMessage> : null}

      {environment ? (
        <>
          <SectionCard title={environment.name ?? environment.environmentId}>
            <InfoGrid>
              <InfoPanel title="Environment state">
                <DataList
                  items={[
                    { label: 'Environment id', value: environment.environmentId },
                    { label: 'Provider', value: environment.provider },
                    { label: 'Profile', value: profile?.name ?? environment.profileId },
                    { label: 'Current state', value: formatStateLabel(environment.state) },
                    { label: 'Actual region', value: environment.region },
                    { label: 'Active operation', value: environment.activeOperationId ?? 'None' },
                    { label: 'Created', value: formatTimestamp(environment.createdAt) },
                    { label: 'Updated', value: formatTimestamp(environment.updatedAt) },
                  ]}
                />
              </InfoPanel>

              <InfoPanel title="Deployment revision">
                {activeDeploymentRevisionId ? (
                  <DataList
                    items={[
                      { label: 'Active revision id', value: activeDeploymentRevisionId },
                      {
                        label: 'Revision status',
                        value: formatStateLabel(
                          environment.activeDeploymentConfiguration?.lifecycleState ?? 'unknown',
                        ),
                      },
                      {
                        label: 'Engine',
                        value: environment.activeDeploymentConfiguration?.engineId ?? 'n/a',
                      },
                      {
                        label: 'Model checkpoint',
                        value:
                          environment.activeDeploymentConfiguration?.resolvedCheckpointRef ?? 'n/a',
                      },
                    ]}
                  />
                ) : (
                  <Body1>No deployment revision is active yet.</Body1>
                )}
                {profile?.knownLimitations.length ? (
                  <>
                    <Title3 as="h3">Known profile limitations</Title3>
                    <ul className={styles.list}>
                      {profile.knownLimitations.map((item) => (
                        <li key={item}>
                          <Body1>{item}</Body1>
                        </li>
                      ))}
                    </ul>
                  </>
                ) : null}
              </InfoPanel>
            </InfoGrid>
          </SectionCard>

          <SectionCard title="Capacity context">
            {environment.capacityContext ? (
              <InfoGrid>
                <InfoPanel>
                  <DataList
                    items={[
                      { label: 'Region evaluated', value: environment.capacityContext.region },
                      { label: 'Assessed at', value: formatTimestamp(environment.capacityContext.assessedAt) },
                      { label: 'Quota status', value: environment.capacityContext.quotaStatus },
                      { label: 'Capacity status', value: environment.capacityContext.capacityStatus },
                    ]}
                  />
                </InfoPanel>
                <InfoPanel title="Fallback and uncertainty notes">
                  <ul className={styles.list}>
                    {environment.capacityContext.notes.map((note) => (
                      <li key={note}>
                        <Body1>{note}</Body1>
                      </li>
                    ))}
                  </ul>
                  {environment.capacityContext.region !== environment.region ? (
                    <StatusMessage intent="warning">
                      The environment is running in {environment.region} even though the last
                      recorded capacity assessment referenced {environment.capacityContext.region}.
                    </StatusMessage>
                  ) : null}
                </InfoPanel>
              </InfoGrid>
            ) : (
              <EmptyState title="No capacity assessment recorded yet">
                This appears once a preview or provisioning request evaluates capacity for this
                environment.
              </EmptyState>
            )}
          </SectionCard>

          <SectionCard title="Provisioned resources">
            {environment.resources.length ? (
              <Table aria-label="Provisioned resources" size="small">
                <TableHeader>
                  <TableRow>
                    <TableHeaderCell>Name</TableHeaderCell>
                    <TableHeaderCell>Type</TableHeaderCell>
                    <TableHeaderCell>State</TableHeaderCell>
                    <TableHeaderCell>Summary</TableHeaderCell>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {environment.resources.map((resource) => (
                    <TableRow key={`${resource.type}-${resource.name}`}>
                      <TableCell>{resource.name}</TableCell>
                      <TableCell>{resource.type}</TableCell>
                      <TableCell>{resource.state}</TableCell>
                      <TableCell>{resource.summary ?? '—'}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            ) : (
              <EmptyState title="No resource state available yet">
                Provider resource details appear here once the environment starts reporting status.
              </EmptyState>
            )}
          </SectionCard>

          {environment.costContext ? (
            <SectionCard title="Cost context">
              <InfoGrid>
                <InfoPanel>
                  <DataList
                    items={[
                      {
                        label: 'Estimated hourly cost',
                        value:
                          environment.costContext.estimatedHourlyUsd !== undefined
                            ? `$${environment.costContext.estimatedHourlyUsd.toFixed(2)}`
                            : 'Not available',
                      },
                    ]}
                  />
                </InfoPanel>
                <InfoPanel title="Notes">
                  {environment.costContext.notes?.length ? (
                    <ul className={styles.list}>
                      {environment.costContext.notes.map((note) => (
                        <li key={note}>
                          <Body1>{note}</Body1>
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <Body1>No additional cost notes recorded.</Body1>
                  )}
                </InfoPanel>
              </InfoGrid>
            </SectionCard>
          ) : null}
        </>
      ) : null}
    </div>
  );
}
