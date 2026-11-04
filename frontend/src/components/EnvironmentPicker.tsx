import { useEffect, useState } from 'react';
import { Dropdown, Field, Option } from '@fluentui/react-components';
import { listEnvironments } from '../services/environmentsApi';
import type { EnvironmentSummary } from '../services/types';
import { StatusMessage, formatStateLabel } from './kit';

type EnvironmentPickerProps = {
  value: string;
  onSelect: (environmentId: string) => void;
  label?: string;
  disabled?: boolean;
  refreshToken?: number;
};

function optionLabel(entry: EnvironmentSummary) {
  return `${entry.environmentId} — ${formatStateLabel(entry.lifecycleState)} (${entry.profileId})`;
}

/**
 * Shared dropdown of known environments so pages never require memorizing or
 * hand-typing an environment id. Selecting an option immediately invokes
 * `onSelect`, letting the caller load the environment right away.
 */
export default function EnvironmentPicker({
  value,
  onSelect,
  label = 'Environment',
  disabled = false,
  refreshToken = 0,
}: EnvironmentPickerProps) {
  const [environments, setEnvironments] = useState<EnvironmentSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string>();

  useEffect(() => {
    let active = true;

    async function load() {
      setLoading(true);
      setError(undefined);

      try {
        const response = await listEnvironments();

        if (!active) {
          return;
        }

        setEnvironments(response.environments);
      } catch (nextError) {
        if (active) {
          setError(
            nextError instanceof Error ? nextError.message : 'Unable to load environments.',
          );
        }
      } finally {
        if (active) {
          setLoading(false);
        }
      }
    }

    void load();

    return () => {
      active = false;
    };
  }, [refreshToken]);

  const hasKnownValue = value ? environments.some((entry) => entry.environmentId === value) : true;
  const selectedEntry = environments.find((entry) => entry.environmentId === value);
  const displayValue = value ? (selectedEntry ? optionLabel(selectedEntry) : `${value} (not in list)`) : '';

  return (
    <div>
      <Field label={label}>
        <Dropdown
          aria-label={label}
          disabled={disabled || loading}
          placeholder={loading ? 'Loading environments…' : 'Select an environment'}
          value={displayValue}
          selectedOptions={value ? [value] : []}
          onOptionSelect={(_event, data) => onSelect(data.optionValue ?? '')}
        >
          {!hasKnownValue && value ? (
            <Option value={value} text={`${value} (not in list)`}>
              {value} (not in list)
            </Option>
          ) : null}
          {environments.map((entry) => (
            <Option key={entry.environmentId} value={entry.environmentId} text={optionLabel(entry)}>
              {optionLabel(entry)}
            </Option>
          ))}
        </Dropdown>
      </Field>
      {error ? (
        <StatusMessage intent="error" title="Couldn't load environments">
          {error}
        </StatusMessage>
      ) : null}
      {!loading && !error && environments.length === 0 ? (
        <StatusMessage intent="info">No environments exist yet. Provision one first.</StatusMessage>
      ) : null}
    </div>
  );
}
