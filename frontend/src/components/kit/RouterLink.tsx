import { Button, Link, type ButtonProps, type LinkProps } from '@fluentui/react-components';
import type { ComponentType, MouseEvent } from 'react';
import { useNavigate } from 'react-router-dom';

// Fluent's Link/Button slot types are a discriminated union keyed on `as`, which TypeScript can't
// re-narrow once props are spread through a wrapper. These wrappers always render an anchor, so
// it's safe (and far simpler) to widen to a generic prop bag locally rather than fight the slot
// typing here; RouterLinkProps/RouterButtonProps still keep the public API fully typed.
const AnchorLink = Link as ComponentType<Record<string, unknown>>;
const AnchorButton = Button as ComponentType<Record<string, unknown>>;

function isPlainLeftClick(event: MouseEvent) {
  return event.button === 0 && !event.metaKey && !event.ctrlKey && !event.shiftKey && !event.altKey;
}

export type RouterLinkProps = Omit<LinkProps, 'href' | 'as' | 'onClick'> & {
  to: string;
  onClick?: (event: MouseEvent<HTMLAnchorElement>) => void;
};

/**
 * Fluent `Link` that navigates via react-router instead of a full page reload.
 * Renders a real `<a href>` so middle-click/ctrl-click "open in new tab" still works.
 */
export function RouterLink({ to, onClick, ...rest }: RouterLinkProps) {
  const navigate = useNavigate();
  return (
    <AnchorLink
      as="a"
      href={to}
      onClick={(event: MouseEvent<HTMLAnchorElement>) => {
        onClick?.(event);
        if (event.defaultPrevented || !isPlainLeftClick(event)) {
          return;
        }
        event.preventDefault();
        navigate(to);
      }}
      {...rest}
    />
  );
}

export type RouterButtonProps = Omit<ButtonProps, 'as' | 'href' | 'onClick'> & {
  to: string;
  onClick?: (event: MouseEvent<HTMLAnchorElement>) => void;
};

/** Fluent `Button` styled as a call-to-action that navigates via react-router. */
export function RouterButton({ to, onClick, ...rest }: RouterButtonProps) {
  const navigate = useNavigate();
  return (
    <AnchorButton
      as="a"
      href={to}
      onClick={(event: MouseEvent<HTMLAnchorElement>) => {
        onClick?.(event);
        if (event.defaultPrevented || !isPlainLeftClick(event)) {
          return;
        }
        event.preventDefault();
        navigate(to);
      }}
      {...rest}
    />
  );
}
