import { Caption1, Title3, makeStyles, tokens } from '@fluentui/react-components';
import type { ReactNode } from 'react';

const useStyles = makeStyles({
  grid: {
    display: 'grid',
    gap: tokens.spacingHorizontalM,
    gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))',
  },
  card: {
    display: 'flex',
    flexDirection: 'column',
    gap: tokens.spacingVerticalXS,
    padding: tokens.spacingVerticalM,
    border: `${tokens.strokeWidthThin} solid ${tokens.colorNeutralStroke2}`,
    borderRadius: tokens.borderRadiusLarge,
    backgroundColor: tokens.colorNeutralBackground2,
  },
  label: {
    color: tokens.colorNeutralForeground3,
  },
});

/** Grid wrapper for MetricCards, replacing the legacy `.metrics-grid`. */
export function MetricGrid({ children }: { children: ReactNode }) {
  const styles = useStyles();
  return <div className={styles.grid}>{children}</div>;
}

/** A single metric tile, replacing the legacy `.metric-card`. */
export function MetricCard({
  label,
  value,
  secondary,
}: {
  label: ReactNode;
  value: ReactNode;
  secondary?: ReactNode;
}) {
  const styles = useStyles();
  return (
    <div className={styles.card}>
      <Caption1 className={styles.label}>{label}</Caption1>
      <Title3>{value}</Title3>
      {secondary ? <Caption1>{secondary}</Caption1> : null}
    </div>
  );
}
