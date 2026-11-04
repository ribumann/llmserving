import { useEffect, useState } from 'react';
import {
  Table,
  TableBody,
  TableCell,
  TableHeader,
  TableHeaderCell,
  TableRow,
} from '@fluentui/react-components';
import { listRuns } from '../services/runsApi';
import type { ExperimentRunType, RunSummary } from '../services/types';
import { EmptyState, LoadingState, RouterLink, SectionCard, StatusMessage, formatStateLabel } from './kit';

type RunHistoryProps = {
  environmentId: string;
  runTypes: ExperimentRunType[];
  reportPathPrefix: '/quality/report' | '/performance/report';
  refreshToken?: number;
};

function formatTimestamp(value?: string | null) {
  if (!value) {
    return 'n/a';
  }

  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString();
}

/**
 * Human-readable list of prior runs for an environment, scoped to the run
 * types relevant to the current page (quality vs. performance), so operators
 * can re-open a previous report instead of memorizing run ids.
 */
export default function RunHistory({
  environmentId,
  runTypes,
  reportPathPrefix,
  refreshToken = 0,
}: RunHistoryProps) {
  const [runs, setRuns] = useState<RunSummary[]>();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string>();

  useEffect(() => {
    if (!environmentId) {
      setRuns(undefined);
      setLoading(false);
      return;
    }

    let active = true;
    setLoading(true);
    setError(undefined);

    listRuns(environmentId)
      .then((response) => {
        if (!active) {
          return;
        }

        setRuns(response.runs.filter((run) => runTypes.includes(run.runType)));
      })
      .catch((nextError: unknown) => {
        if (active) {
          setError(
            nextError instanceof Error ? nextError.message : 'Unable to load prior runs.',
          );
        }
      })
      .finally(() => {
        if (active) {
          setLoading(false);
        }
      });

    return () => {
      active = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [environmentId, refreshToken]);

  if (!environmentId) {
    return null;
  }

  return (
    <SectionCard title="Prior runs" description="Re-open a previous run's report instead of re-running it.">
      {loading ? <LoadingState label="Loading run history…" /> : null}
      {error ? (
        <StatusMessage intent="error" title="Couldn't load prior runs">
          {error}
        </StatusMessage>
      ) : null}
      {!loading && !error ? (
        runs && runs.length ? (
          <Table aria-label="Prior runs">
            <TableHeader>
              <TableRow>
                <TableHeaderCell>Reference</TableHeaderCell>
                <TableHeaderCell>Status</TableHeaderCell>
                <TableHeaderCell>Model / engine</TableHeaderCell>
                <TableHeaderCell>Started</TableHeaderCell>
                <TableHeaderCell>Ended</TableHeaderCell>
                <TableHeaderCell>Action</TableHeaderCell>
              </TableRow>
            </TableHeader>
            <TableBody>
              {runs.map((run) => (
                <TableRow key={run.runId}>
                  <TableCell>{run.testDefinitionRef ?? run.runId}</TableCell>
                  <TableCell>{formatStateLabel(run.status)}</TableCell>
                  <TableCell>
                    {run.configuration?.resolvedCheckpointRef ?? 'n/a'}
                    {run.configuration?.engineId ? ` · ${run.configuration.engineId}` : ''}
                  </TableCell>
                  <TableCell>{formatTimestamp(run.startedAt)}</TableCell>
                  <TableCell>{formatTimestamp(run.endedAt)}</TableCell>
                  <TableCell>
                    <RouterLink
                      to={`${reportPathPrefix}/${run.runId}?environmentId=${encodeURIComponent(environmentId)}`}
                    >
                      Open report
                    </RouterLink>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        ) : (
          <EmptyState title="No prior runs yet">
            Runs you start for this environment will show up here so you can reopen their reports later.
          </EmptyState>
        )
      ) : null}
    </SectionCard>
  );
}
