import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MarkdownRenderer } from './MarkdownRenderer';

describe('MarkdownRenderer', () => {
  it('renders plain markdown text', () => {
    render(<MarkdownRenderer content="Auth uses **JWT** tokens." />);
    expect(screen.getByText(/Auth uses/)).toBeInTheDocument();
  });

  it('renders a fenced code block without crashing', async () => {
    render(<MarkdownRenderer content={'```python\ndef login():\n    return True\n```'} />);
    expect(await screen.findByText(/def login/)).toBeInTheDocument();
  });

  it('renders inline code', () => {
    render(<MarkdownRenderer content="Call `login()` to authenticate." />);
    expect(screen.getByText('login()')).toBeInTheDocument();
  });
});
