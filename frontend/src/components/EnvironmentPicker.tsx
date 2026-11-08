import { useEffect, useState } from 'react';
import { Dropdown, Field, Option } from '@fluentui/react-components';
import { listEnvironments } from '../services/environmentsApi';
import type { EnvironmentSummary } from '../services/types';
import { StatusMessage } from './kit';
import { environmentOptionLabel, visibleEnvironments } from './environmentOptions';

type EnvironmentPickerProps = {
  value: string;
  onSelect: (environmentId: string) => void;
  label?: string;
  disabled?: boolean;
  refreshToken?: number;
};

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
  const [showArchived, setShowArchived] = useState(false);

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
  const displayValue = value ? (selectedEntry ? environmentOptionLabel(selectedEntry) : `${value} (not in list)`) : '';
  const visible = visibleEnvironments(environments, showArchived, value);

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
          {visible.map((entry) => (
            <Option key={entry.environmentId} value={entry.environmentId} text={environmentOptionLabel(entry)}>
              {environmentOptionLabel(entry)}
            </Option>
          ))}
        </Dropdown>
      </Field>
      {environments.some((entry) => entry.lifecycleState === 'torn_down') ? (
        <label><input type="checkbox" checked={showArchived} onChange={(event) => setShowArchived(event.target.checked)} /> Show torn-down environments</label>
      ) : null}
      {!loading && !error && environments.length > 0 && visible.length === 0 ? (
        <StatusMessage intent="info">No active environments. Show torn-down environments to view their history.</StatusMessage>
      ) : null}
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
