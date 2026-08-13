import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MessageBubble } from './MessageBubble';
import type { ChatMessage } from '../store/useChatStore';

function makeMessage(overrides: Partial<ChatMessage>): ChatMessage {
  return {
    id: '1',
    role: 'assistant',
    content: '',
    timestamp: new Date('2026-01-01T00:00:00Z'),
    ...overrides,
  };
}

describe('MessageBubble', () => {
  it('shows the typing indicator while pending with no content yet', () => {
    render(<MessageBubble message={makeMessage({ status: 'pending', content: '' })} onRetry={vi.fn()} />);
    expect(screen.getByRole('status', { name: /assistant is typing/i })).toBeInTheDocument();
  });

  it('renders the growing answer instead of the typing indicator once tokens arrive, while still pending', () => {
    render(<MessageBubble message={makeMessage({ status: 'pending', content: 'Auth uses' })} onRetry={vi.fn()} />);
    expect(screen.queryByRole('status', { name: /assistant is typing/i })).not.toBeInTheDocument();
    expect(screen.getByText('Auth uses')).toBeInTheDocument();
  });

  it('shows source citations and timestamp once complete', () => {
    render(
      <MessageBubble
        message={makeMessage({
          status: 'complete',
          content: 'Auth uses JWT.',
          sourceFiles: ['src/auth.py'],
          retrievedChunks: 2,
        })}
        onRetry={vi.fn()}
      />
    );
    expect(screen.getByText('src/auth.py')).toBeInTheDocument();
  });

  it('shows a retry button when errored', () => {
    const onRetry = vi.fn();
    render(<MessageBubble message={makeMessage({ status: 'error', content: 'Network down' })} onRetry={onRetry} />);
    screen.getByRole('button', { name: /retry/i }).click();
    expect(onRetry).toHaveBeenCalledWith('1');
  });
});
