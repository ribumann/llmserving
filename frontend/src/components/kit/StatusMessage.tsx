import { MessageBar, MessageBarBody, MessageBarTitle } from '@fluentui/react-components';
import type { ReactNode } from 'react';

export type StatusIntent = 'info' | 'warning' | 'error' | 'success';

export type StatusMessageProps = {
  intent?: StatusIntent;
  title?: string;
  children: ReactNode;
};

/**
 * Replacement for the legacy `.status-banner status-{info,warning,error,success}` divs.
 * Maps directly onto Fluent's MessageBar intents.
 */
export default function StatusMessage({ intent = 'info', title, children }: StatusMessageProps) {
  return (
    <MessageBar intent={intent}>
      <MessageBarBody>
        {title ? <MessageBarTitle>{title}</MessageBarTitle> : null}
        {children}
      </MessageBarBody>
    </MessageBar>
  );
}
