import { useEffect, useState } from 'react';
import {
  Card,
  CardHeader,
  Subtitle2,
  Text,
  makeStyles,
  tokens,
} from '@fluentui/react-components';
import { CloudArrowUp20Regular, Rocket20Regular } from '@fluentui/react-icons';
import { listEnvironments } from '../services/environmentsApi';
import type { EnvironmentSummary } from '../services/types';
import { SignInLink } from '../components/OperatorAccess';
import {
  EmptyState,
  LoadingState,
  PageHeader,
  RouterButton,
  RouterLink,
  StatusBadge,
  StatusMessage,
  formatStateLabel,
  statusTone,
} from '../components/kit';

const useStyles = makeStyles({
  sectionTitle: {
    display: 'block',
    marginBottom: tokens.spacingVerticalM,
  },
  grid: {
    display: 'grid',
    gap: tokens.spacingHorizontalM,
    gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))',
    marginBottom: tokens.spacingVerticalXXL,
  },
  card: {
    display: 'flex',
    flexDirection: 'column',
    gap: tokens.spacingVerticalS,
    padding: tokens.spacingVerticalL,
  },
  envHeader: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    gap: tokens.spacingHorizontalS,
  },
  envMeta: {
    color: tokens.colorNeutralForeground3,
  },
  envActions: {
    display: 'flex',
    flexWrap: 'wrap',
    gap: tokens.spacingHorizontalM,
  },
});

const GETTING_STARTED = [
  {
    to: '/provision',
    icon: <CloudArrowUp20Regular />,
    title: 'Provision an environment',
    description:
      'Pick a deployment profile, preview capacity and quota, and stand up a fresh environment.',
  },
  {
    to: '/deploy',
    icon: <Rocket20Regular />,
    title: 'Deploy a model',
    description:
      'Choose a model and inference configuration, then deploy it into a provisioned environment.',
  },
];

/**
 * The app's landing page. Replaces the old "operator workflow skeleton" placeholder with a real
 * overview: quick entry points to start a new workflow, plus a live list of environments that
 * already exist so an operator can jump straight back into one instead of hunting for an id.
 */
export default function OverviewPage({
  authenticated,
}: {
  authenticated: boolean;
}) {
  const styles = useStyles();
  const [environments, setEnvironments] = useState<EnvironmentSummary[] | null>(
    null,
  );
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!authenticated) {
      setEnvironments(null);
      setError(null);
      return;
    }
    let active = true;
    listEnvironments()
      .then((response) => {
        if (active) {
          setEnvironments(response.environments);
        }
      })
      .catch((err) => {
        if (active) {
          setError(
            err instanceof Error ? err.message : 'Failed to load environments.',
          );
        }
      });
    return () => {
      active = false;
    };
  }, [authenticated]);

  return (
    <section>
      <PageHeader
        title="Overview"
        description="A guided operator workflow for provisioning, deploying, exercising, evaluating, comparing, and tearing down LLM serving environments on Azure."
      />

      {!authenticated ? (
        <EmptyState title="Explore the workflow" actions={<SignInLink />}>
          Follow the navigation to learn how an environment moves from
          provisioning and model deployment to prompts, quality and performance
          runs, comparison, and teardown. No live environments, configuration,
          history or reports are shown publicly. Sign in with an approved
          account to work with real resources.
        </EmptyState>
      ) : null}

      <Subtitle2 as="h3" className={styles.sectionTitle}>
        Get started
      </Subtitle2>
      <div className={styles.grid}>
        {GETTING_STARTED.map((step) => (
          <Card className={styles.card} key={step.to}>
            <CardHeader
              image={step.icon}
              header={<Text weight="semibold">{step.title}</Text>}
            />
            <Text>{step.description}</Text>
            <RouterLink to={step.to}>
              Go to {step.title.charAt(0).toLowerCase() + step.title.slice(1)}
            </RouterLink>
          </Card>
        ))}
      </div>

      {authenticated ? (
        <>
          <Subtitle2 as="h3" className={styles.sectionTitle}>
            Your environments
          </Subtitle2>
          {error ? (
            <StatusMessage intent="error" title="Couldn't load environments">
              {error}
            </StatusMessage>
          ) : null}
          {!error && environments === null ? (
            <LoadingState label="Loading environments…" />
          ) : null}
          {!error && environments && environments.length === 0 ? (
            <EmptyState
              title="No environments yet"
              actions={
                <RouterButton to="/provision" appearance="primary">
                  Provision your first environment
                </RouterButton>
              }
            >
              Provision an environment to start deploying and exercising models.
            </EmptyState>
          ) : null}
          {environments && environments.length > 0 ? (
            <div className={styles.grid}>
              {environments.map((env) => (
                <Card className={styles.card} key={env.environmentId}>
                  <div className={styles.envHeader}>
                    <Text weight="semibold">{env.environmentId}</Text>
                    <StatusBadge tone={statusTone(env.lifecycleState)}>
                      {formatStateLabel(env.lifecycleState)}
                    </StatusBadge>
                  </div>
                  <Text className={styles.envMeta}>
                    {env.profileId} · {env.provider} · {env.region}
                  </Text>
                  {env.activeDeploymentConfiguration ? (
                    <Text className={styles.envMeta}>
                      Deployed:{' '}
                      {env.activeDeploymentConfiguration
                        .resolvedCheckpointRef ?? 'n/a'}{' '}
                      · {env.activeDeploymentConfiguration.engineId ?? 'n/a'}
                    </Text>
                  ) : null}
                  <div className={styles.envActions}>
                    <RouterLink to={`/environments/${env.environmentId}`}>
                      View detail
                    </RouterLink>
                    <RouterLink
                      to={`/exercise?environmentId=${env.environmentId}`}
                    >
                      Exercise
                    </RouterLink>
                    <RouterLink
                      to={`/quality/run?environmentId=${env.environmentId}`}
                    >
                      Quality run
                    </RouterLink>
                    <RouterLink
                      to={`/performance/run?environmentId=${env.environmentId}`}
                    >
                      Performance run
                    </RouterLink>
                  </div>
                </Card>
              ))}
            </div>
          ) : null}
        </>
      ) : null}
    </section>
  );
}
