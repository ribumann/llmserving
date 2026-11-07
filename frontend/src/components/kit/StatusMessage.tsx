import {
  MessageBar,
  MessageBarBody,
  MessageBarTitle,
  makeStyles,
} from '@fluentui/react-components';
import type { ReactNode } from 'react';

export type StatusIntent = 'info' | 'warning' | 'error' | 'success';

export type StatusMessageProps = {
  intent?: StatusIntent;
  title?: string;
  children: ReactNode;
};

const useStyles = makeStyles({
  body: { minWidth: 0, overflowWrap: 'anywhere' },
});

/**
 * Replacement for the legacy `.status-banner status-{info,warning,error,success}` divs.
 * Maps directly onto Fluent's MessageBar intents.
 */
export default function StatusMessage({
  intent = 'info',
  title,
  children,
}: StatusMessageProps) {
  const styles = useStyles();
  return (
    <MessageBar intent={intent}>
      <MessageBarBody className={styles.body}>
        {title ? <MessageBarTitle>{title}</MessageBarTitle> : null}
        {children}
      </MessageBarBody>
    </MessageBar>
  );
}
