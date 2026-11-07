import { useCallback, useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { Button, Field, Textarea, makeStyles, tokens } from '@fluentui/react-components';
import EnvironmentPicker from '../components/EnvironmentPicker';
import { ApiError } from '../services/apiClient';
import { submitPrompt } from '../services/deploymentsApi';
import { getEnvironment } from '../services/environmentsApi';
import type { DemoEnvironment, PromptResponse } from '../services/types';
import {
  DataList,
  EmptyState,
  InfoGrid,
  InfoPanel,
  MetricCard,
  MetricGrid,
  PageHeader,
  RouterLink,
  SectionCard,
  StatusMessage,
  formatMetricValue,
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
  exchangeStack: {
    display: 'flex',
    flexDirection: 'column',
    gap: tokens.spacingVerticalM,
  },
});

type PromptExchange = {
  id: string;
  prompt: string;
  response: PromptResponse;
  submittedAt: string;
};

function formatTimestamp(value?: string) {
  if (!value) {
    return 'n/a';
  }

  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString();
}

function parseParameters(value: string) {
  try {
    const parsed = JSON.parse(value) as unknown;

    if (!parsed || Array.isArray(parsed) || typeof parsed !== 'object') {
      throw new Error('Parameters must be a JSON object.');
    }

    return parsed as Record<string, unknown>;
  } catch (error) {
    throw new Error(error instanceof Error ? error.message : 'Parameters JSON is invalid.');
  }
}

function getPromptErrorMessage(error: unknown, environmentId: string) {
  if (error instanceof ApiError) {
    switch (error.code) {
      case 'no_ready_deployment':
        return `No ready deployment is active for this environment. Open Deploy to activate one before retrying: /deploy?environmentId=${environmentId}`;
      case 'environment_busy':
        return 'An operation is currently running against this environment. Try again shortly.';
      default:
        return error.message;
    }
  }

  return error instanceof Error ? error.message : 'Prompt submission failed.';
}

export default function ExercisePage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const styles = useStyles();
  const [environmentId, setEnvironmentId] = useState(searchParams.get('environmentId') ?? '');
  const [environment, setEnvironment] = useState<DemoEnvironment>();
  const [environmentLoading, setEnvironmentLoading] = useState(false);
  const [environmentError, setEnvironmentError] = useState<string>();
  const [prompt, setPrompt] = useState('');
  const [parametersText, setParametersText] = useState('{\n  "temperature": 0.2\n}');
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string>();
  const [history, setHistory] = useState<PromptExchange[]>([]);

  const handleLoadEnvironment = useCallback(
    async (nextEnvironmentId = environmentId) => {
    if (!nextEnvironmentId.trim()) {
      setEnvironmentError('Enter an environment id to load the active deployment context.');
      return;
    }

    setEnvironmentLoading(true);
    setEnvironmentError(undefined);

    try {
      const response = await getEnvironment(nextEnvironmentId.trim());
      setEnvironment(response);
      setEnvironmentId(response.environmentId);
      setSearchParams({ environmentId: response.environmentId });
    } catch (error) {
      setEnvironmentError(
        error instanceof Error ? error.message : 'Failed to load the selected environment.',
      );
      setEnvironment(undefined);
    } finally {
      setEnvironmentLoading(false);
    }
    },
    [environmentId, setSearchParams],
  );

  async function handleSubmitPrompt() {
    if (!environmentId.trim() || !prompt.trim()) {
      return;
    }

    setSubmitting(true);
    setSubmitError(undefined);

    try {
      const response = await submitPrompt(environmentId.trim(), {
        prompt: prompt.trim(),
        parameters: parseParameters(parametersText),
      });

      setHistory((existing) => [
        {
          id: `${response.deploymentRevisionId}-${Date.now()}`,
          prompt: prompt.trim(),
          response,
          submittedAt: new Date().toISOString(),
        },
        ...existing,
      ]);
      setPrompt('');
      await handleLoadEnvironment(environmentId.trim());
    } catch (error) {
      setSubmitError(getPromptErrorMessage(error, environmentId.trim()));
    } finally {
      setSubmitting(false);
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

  return (
    <div className={styles.stack}>
      <PageHeader
        eyebrow="Operate"
        title="Exercise a deployment"
        description="Submit ad hoc prompts against the active ready deployment and review the response text, timing breakdown, and revision traceability."
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
          {environmentId ? (
            <RouterLink to={`/deploy?environmentId=${environmentId}`}>Open deploy page</RouterLink>
          ) : null}
        </div>

        {environment ? (
          <InfoGrid>
            <InfoPanel title="Deployment context">
              <DataList
                items={[
                  { label: 'Name', value: environment.name ?? environment.environmentId },
                  { label: 'Lifecycle', value: environment.state },
                  {
                    label: 'Active deployment revision',
                    value: environment.activeDeploymentRevisionId ?? environment.activeRevisionId ?? 'None',
                  },
                  { label: 'Updated', value: formatTimestamp(environment.updatedAt) },
                ]}
              />
            </InfoPanel>
          </InfoGrid>
        ) : null}
      </SectionCard>

      <SectionCard title="2. Prompt console">
        <div className={styles.formGrid}>
          <Field label="Prompt">
            <Textarea
              rows={6}
              value={prompt}
              onChange={(event) => setPrompt(event.target.value)}
              placeholder="Explain why this environment is a good demo target."
            />
          </Field>
          <Field label="Parameters JSON">
            <Textarea
              rows={6}
              value={parametersText}
              onChange={(event) => setParametersText(event.target.value)}
            />
          </Field>
        </div>

        {submitError ? <StatusMessage intent="error">{submitError}</StatusMessage> : null}
        <div className={styles.actions}>
          <Button
            appearance="primary"
            onClick={() => void handleSubmitPrompt()}
            disabled={!environmentId.trim() || !prompt.trim() || submitting}
          >
            {submitting ? 'Submitting prompt…' : 'Submit prompt'}
          </Button>
        </div>
      </SectionCard>

      <SectionCard
        title="3. Session prompt history"
        description="Prompts are not saved. Closing or refreshing this page clears the session history."
      >
        {history.length ? (
          <div className={styles.exchangeStack}>
            {history.map((exchange) => (
              <InfoPanel key={exchange.id}>
                <DataList
                  items={[
                    { label: 'Submitted', value: formatTimestamp(exchange.submittedAt) },
                    { label: 'Prompt', value: exchange.prompt },
                    { label: 'Response', value: exchange.response.responseText },
                    { label: 'Active revision', value: exchange.response.activeRevision.deploymentRevisionId },
                  ]}
                />
                <MetricGrid>
                  <MetricCard label="Time to first token" value={`${formatMetricValue(exchange.response.timing.ttftMs)} ms`} />
                  <MetricCard
                    label="Inter-token latency (avg)"
                    value={`${formatMetricValue(exchange.response.timing.interTokenLatencyMsAvg)} ms`}
                  />
                  <MetricCard label="Total latency" value={`${formatMetricValue(exchange.response.timing.totalLatencyMs)} ms`} />
                </MetricGrid>
              </InfoPanel>
            ))}
          </div>
        ) : (
          <EmptyState title="No prompts submitted in this browser session yet">
            Submit a prompt above to see its response, timing breakdown, and revision traceability
            here.
          </EmptyState>
        )}
      </SectionCard>
    </div>
  );
}
