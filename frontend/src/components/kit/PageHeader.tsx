import { Text, Title2, makeStyles, tokens } from '@fluentui/react-components';
import type { ReactNode } from 'react';

const useStyles = makeStyles({
  root: {
    display: 'flex',
    flexDirection: 'column',
    gap: tokens.spacingVerticalS,
    marginBottom: tokens.spacingVerticalL,
  },
  eyebrow: {
    color: tokens.colorBrandForeground1,
    textTransform: 'uppercase',
    letterSpacing: '0.08em',
    fontWeight: tokens.fontWeightSemibold,
  },
  description: {
    maxWidth: '56rem',
    color: tokens.colorNeutralForeground2,
  },
  actions: {
    display: 'flex',
    gap: tokens.spacingHorizontalS,
    flexWrap: 'wrap',
    marginTop: tokens.spacingVerticalXS,
  },
});

export type PageHeaderProps = {
  eyebrow?: string;
  title: string;
  description?: ReactNode;
  actions?: ReactNode;
};

/** Standard page title block: eyebrow + heading + helper copy + primary actions. */
export default function PageHeader({ eyebrow, title, description, actions }: PageHeaderProps) {
  const styles = useStyles();
  return (
    <header className={styles.root}>
      {eyebrow ? (
        <Text size={200} className={styles.eyebrow}>
          {eyebrow}
        </Text>
      ) : null}
      <Title2 as="h2">{title}</Title2>
      {description ? <Text className={styles.description}>{description}</Text> : null}
      {actions ? <div className={styles.actions}>{actions}</div> : null}
    </header>
  );
}
