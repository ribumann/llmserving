import { useEffect, useState } from 'react';
import {
  Button,
  Table,
  TableBody,
  TableCell,
  TableHeader,
  TableHeaderCell,
  TableRow,
  Text,
} from '@fluentui/react-components';
import {
  listInferenceConfigurations,
  listModelConfigurations,
} from '../services/deploymentsApi';
import type {
  InferenceConfigurationVersion,
  ModelConfigurationVersion,
} from '../services/types';
import { EmptyState, InfoGrid, InfoPanel, LoadingState, SectionCard, StatusMessage } from './kit';

type ConfigVersionHistoryProps = {
  environmentId: string;
  refreshToken?: number;
  selectedInferenceConfigId?: string;
  selectedModelConfigId?: string;
  onSelectInferenceConfiguration?: (configuration: InferenceConfigurationVersion) => void;
  onSelectModelConfiguration?: (configuration: ModelConfigurationVersion) => void;
};

function formatTimestamp(value?: string) {
  if (!value) {
    return 'n/a';
  }

  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString();
}

export default function ConfigVersionHistory({
  environmentId,
  refreshToken = 0,
  selectedInferenceConfigId,
  selectedModelConfigId,
  onSelectInferenceConfiguration,
  onSelectModelConfiguration,
}: ConfigVersionHistoryProps) {
  const [modelConfigurations, setModelConfigurations] = useState<ModelConfigurationVersion[]>([]);
  const [inferenceConfigurations, setInferenceConfigurations] = useState<
    InferenceConfigurationVersion[]
  >([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string>();

  useEffect(() => {
    let cancelled = false;

    async function load() {
      setLoading(true);
      setError(undefined);

      try {
        const [modelResponse, inferenceResponse] = await Promise.all([
          listModelConfigurations(environmentId),
          listInferenceConfigurations(environmentId),
        ]);

        if (cancelled) {
          return;
        }

        setModelConfigurations(modelResponse.items);
        setInferenceConfigurations(inferenceResponse.items);
      } catch (nextError) {
        if (!cancelled) {
          setError(
            nextError instanceof Error
              ? nextError.message
              : 'Failed to load configuration version history.',
          );
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    }

    void load();

    return () => {
      cancelled = true;
    };
  }, [environmentId, refreshToken]);

  return (
    <SectionCard
      title="Configuration version history"
      description="Every save creates a new immutable version. Re-select an earlier version to redeploy it explicitly."
    >
      {loading ? <LoadingState label="Loading configuration history…" /> : null}
      {error ? (
        <StatusMessage intent="error" title="Couldn't load configuration history">
          {error}
        </StatusMessage>
      ) : null}

      {!loading && !error ? (
        <InfoGrid>
          <InfoPanel title="Model configurations">
            {modelConfigurations.length ? (
              <Table aria-label="Model configuration versions" size="small">
                <TableHeader>
                  <TableRow>
                    <TableHeaderCell>Version</TableHeaderCell>
                    <TableHeaderCell>Checkpoint</TableHeaderCell>
                    <TableHeaderCell>Created</TableHeaderCell>
                    <TableHeaderCell>Action</TableHeaderCell>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {modelConfigurations.map((configuration) => (
                    <TableRow key={configuration.modelConfigId}>
                      <TableCell>
                        v{configuration.version}
                        {selectedModelConfigId === configuration.modelConfigId ? ' (selected)' : ''}
                      </TableCell>
                      <TableCell>
                        <Text block>{configuration.catalogEntryId}</Text>
                        <Text size={200}>{configuration.resolvedCheckpointRef}</Text>
                      </TableCell>
                      <TableCell>{formatTimestamp(configuration.createdAt)}</TableCell>
                      <TableCell>
                        <Button
                          size="small"
                          onClick={() => onSelectModelConfiguration?.(configuration)}
                        >
                          Use version
                        </Button>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            ) : (
              <EmptyState title="No model configuration versions yet">
                Create one from the Deploy page to see it listed here.
              </EmptyState>
            )}
          </InfoPanel>

          <InfoPanel title="Inference configurations">
            {inferenceConfigurations.length ? (
              <Table aria-label="Inference configuration versions" size="small">
                <TableHeader>
                  <TableRow>
                    <TableHeaderCell>Version</TableHeaderCell>
                    <TableHeaderCell>Engine</TableHeaderCell>
                    <TableHeaderCell>Created</TableHeaderCell>
                    <TableHeaderCell>Action</TableHeaderCell>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {inferenceConfigurations.map((configuration) => (
                    <TableRow key={configuration.inferenceConfigId}>
                      <TableCell>
                        v{configuration.version}
                        {selectedInferenceConfigId === configuration.inferenceConfigId
                          ? ' (selected)'
                          : ''}
                      </TableCell>
                      <TableCell>{configuration.engineId}</TableCell>
                      <TableCell>{formatTimestamp(configuration.createdAt)}</TableCell>
                      <TableCell>
                        <Button
                          size="small"
                          onClick={() => onSelectInferenceConfiguration?.(configuration)}
                        >
                          Use version
                        </Button>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            ) : (
              <EmptyState title="No inference configuration versions yet">
                Create one from the Deploy page to see it listed here.
              </EmptyState>
            )}
          </InfoPanel>
        </InfoGrid>
      ) : null}
    </SectionCard>
  );
}
