import { StatusMessage } from './kit';

type ComparabilityWarningProps = {
  provider?: 'azure' | 'local';
};

export default function ComparabilityWarning({ provider }: ComparabilityWarningProps) {
  if (provider !== 'local') {
    return null;
  }

  return (
    <StatusMessage intent="warning">
      Local Ollama results are <strong>not directly comparable</strong> to Azure-hosted results
      because the provider runtime and hardware are different.
    </StatusMessage>
  );
}
