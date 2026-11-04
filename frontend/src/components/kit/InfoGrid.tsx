import { Caption1, Text, makeStyles, tokens } from '@fluentui/react-components';
import type { ReactNode } from 'react';

const useStyles = makeStyles({
  grid: {
    display: 'grid',
    gap: tokens.spacingHorizontalM,
    gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))',
  },
  panel: {
    display: 'flex',
    flexDirection: 'column',
    gap: tokens.spacingVerticalS,
    padding: tokens.spacingVerticalM,
    border: `${tokens.strokeWidthThin} solid ${tokens.colorNeutralStroke2}`,
    borderRadius: tokens.borderRadiusLarge,
    backgroundColor: tokens.colorNeutralBackground2,
  },
  panelTitle: {
    fontWeight: tokens.fontWeightSemibold,
  },
  list: {
    display: 'grid',
    gap: tokens.spacingVerticalS,
    margin: 0,
  },
  item: {
    display: 'grid',
    gap: tokens.spacingVerticalXXS,
    margin: 0,
  },
  term: {
    color: tokens.colorNeutralForeground3,
  },
  definition: {
    margin: 0,
  },
});

/** Grid wrapper for one or more InfoPanel cards, replacing the legacy `.info-grid`. */
export function InfoGrid({ children }: { children: ReactNode }) {
  const styles = useStyles();
  return <div className={styles.grid}>{children}</div>;
}

/** Bordered card grouping a set of label/value pairs, replacing the legacy `.info-panel`. */
export function InfoPanel({ title, children }: { title?: ReactNode; children: ReactNode }) {
  const styles = useStyles();
  return (
    <div className={styles.panel}>
      {title ? <Text className={styles.panelTitle}>{title}</Text> : null}
      {children}
    </div>
  );
}

export type DataListItem = {
  label: ReactNode;
  value: ReactNode;
};

/** Label/value list replacing the legacy `dl`/`dt`/`dd` info-grid markup. */
export function DataList({ items }: { items: DataListItem[] }) {
  const styles = useStyles();
  return (
    <dl className={styles.list}>
      {items.map((item, index) => (
        <div className={styles.item} key={index}>
          <dt className={styles.term}>
            <Caption1>{item.label}</Caption1>
          </dt>
          <dd className={styles.definition}>{item.value}</dd>
        </div>
      ))}
    </dl>
  );
}
