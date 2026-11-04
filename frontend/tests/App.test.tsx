import { render, screen, within } from '@testing-library/react';
import App from '../src/App';

describe('App shell', () => {
  it('renders the operator shell', () => {
    render(<App />);

    expect(
      screen.getByRole('heading', {
        name: /azure llm serving demo/i,
      }),
    ).toBeInTheDocument();

    const nav = screen.getByRole('navigation', { name: /primary/i });
    expect(within(nav).getByRole('link', { name: /provision/i })).toBeInTheDocument();
  });
});
