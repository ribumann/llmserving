import { Body1, Spinner, Title3, makeStyles, tokens } from '@fluentui/react-components';
import type { ReactNode } from 'react';

const useStyles = makeStyles({
  root: {
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'flex-start',
    gap: tokens.spacingVerticalS,
    padding: `${tokens.spacingVerticalXL} 0`,
    maxWidth: '40rem',
  },
  body: {
    color: tokens.colorNeutralForeground2,
  },
  actions: {
    display: 'flex',
    gap: tokens.spacingHorizontalS,
    marginTop: tokens.spacingVerticalXS,
  },
});

export type EmptyStateProps = {
  title: string;
  children?: ReactNode;
  actions?: ReactNode;
};

/**
 * Explains what to do next instead of a bare "No data" message. Use for every
 * empty list/table/result state across the app.
 */
export function EmptyState({ title, children, actions }: EmptyStateProps) {
  const styles = useStyles();
  return (
    <div className={styles.root}>
      <Title3 as="h3">{title}</Title3>
      {children ? <Body1 className={styles.body}>{children}</Body1> : null}
      {actions ? <div className={styles.actions}>{actions}</div> : null}
    </div>
  );
}

export type LoadingStateProps = {
  label: string;
};

/** Spinner + explanatory label, replacing bare "Loading…" text. */
export function LoadingState({ label }: LoadingStateProps) {
  const styles = useStyles();
  return (
    <div className={styles.root}>
      <Spinner size="small" label={label} />
    </div>
  );
}
