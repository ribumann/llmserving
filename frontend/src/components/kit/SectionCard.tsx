import { Card, CardHeader, Subtitle2, Text, makeStyles, tokens } from '@fluentui/react-components';
import type { ReactNode } from 'react';

const useStyles = makeStyles({
  card: {
    display: 'flex',
    flexDirection: 'column',
    gap: tokens.spacingVerticalM,
    padding: tokens.spacingVerticalL,
  },
});

export type SectionCardProps = {
  title: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
  children?: ReactNode;
};

/** Replacement for the legacy `.card`/page-section pattern used throughout every page. */
export default function SectionCard({ title, description, actions, children }: SectionCardProps) {
  const styles = useStyles();
  return (
    <Card className={styles.card}>
      <CardHeader
        header={<Subtitle2 as="h3">{title}</Subtitle2>}
        description={description ? <Text>{description}</Text> : undefined}
        action={actions ? <>{actions}</> : undefined}
      />
      {children}
    </Card>
  );
}
