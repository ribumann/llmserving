import { Badge, type BadgeProps } from '@fluentui/react-components';
import type { ReactNode } from 'react';

export type StatusTone = 'success' | 'warning' | 'error' | 'info' | 'neutral' | 'brand';

const TONE_TO_COLOR: Record<StatusTone, BadgeProps['color']> = {
  success: 'success',
  warning: 'warning',
  error: 'danger',
  info: 'informative',
  neutral: 'subtle',
  brand: 'brand',
};

export type StatusBadgeProps = {
  tone: StatusTone;
  children: ReactNode;
};

/** Replacement for the legacy `.badge`/`.status-pill` classes, mapped onto Fluent Badge colors. */
export default function StatusBadge({ tone, children }: StatusBadgeProps) {
  return (
    <Badge appearance="tint" color={TONE_TO_COLOR[tone]} shape="rounded" size="medium">
      {children}
    </Badge>
  );
}
