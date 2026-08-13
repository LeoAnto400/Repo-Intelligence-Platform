import { beforeEach, describe, expect, it, vi } from 'vitest';
import { useChatStore } from './useChatStore';
import { queryService } from '../services/query';
import { queryStreamClient } from '../services/queryStream';

vi.mock('../services/query', () => ({
  queryService: { queryRepository: vi.fn() },
}));

vi.mock('../services/queryStream', () => ({
  queryStreamClient: { query: vi.fn() },
}));

describe('useChatStore', () => {
  beforeEach(() => {
    useChatStore.setState({ messages: [], isLoading: false });
    vi.mocked(queryService.queryRepository).mockReset();
    vi.mocked(queryStreamClient.query).mockReset();
  });

  it('streams tokens progressively then finalizes with the done event answer', async () => {
    const contentSnapshots: string[] = [];
    const unsubscribe = useChatStore.subscribe((state) => {
      const assistant = state.messages.find((m) => m.role === 'assistant');
      if (assistant) contentSnapshots.push(assistant.content);
    });

    vi.mocked(queryStreamClient.query).mockImplementation(async (_question, _history, handlers) => {
      handlers.onToken('Auth ');
      handlers.onToken('uses JWT.');
      return { answer: 'Auth uses JWT tokens.', sourceFiles: ['src/auth.py'], retrievedChunks: 2 };
    });

    await useChatStore.getState().sendMessage('How does auth work?');
    unsubscribe();

    expect(contentSnapshots).toContain('Auth ');
    expect(contentSnapshots).toContain('Auth uses JWT.');

    const { messages, isLoading } = useChatStore.getState();
    expect(isLoading).toBe(false);
    expect(messages).toHaveLength(2);
    expect(messages[0]).toMatchObject({ role: 'user', content: 'How does auth work?', status: 'complete' });
    expect(messages[1]).toMatchObject({
      role: 'assistant',
      status: 'complete',
      content: 'Auth uses JWT tokens.',
      sourceFiles: ['src/auth.py'],
      retrievedChunks: 2,
    });
    expect(queryService.queryRepository).not.toHaveBeenCalled();
  });

  it('sends no history for the first question in a fresh conversation', async () => {
    vi.mocked(queryStreamClient.query).mockResolvedValue({ answer: 'Answer.', sourceFiles: [], retrievedChunks: 0 });

    await useChatStore.getState().sendMessage('What does this repo do?');

    expect(queryStreamClient.query).toHaveBeenCalledWith('What does this repo do?', [], expect.anything());
  });

  it('sends prior completed turns as history on a follow-up question', async () => {
    vi.mocked(queryStreamClient.query).mockResolvedValue({
      answer: "It's a FastAPI backend.",
      sourceFiles: [],
      retrievedChunks: 0,
    });
    await useChatStore.getState().sendMessage('What does this repo do?');
    vi.mocked(queryStreamClient.query).mockClear();

    vi.mocked(queryStreamClient.query).mockResolvedValue({ answer: 'It uses JWT.', sourceFiles: [], retrievedChunks: 0 });
    await useChatStore.getState().sendMessage('How does it handle auth?');

    expect(queryStreamClient.query).toHaveBeenCalledWith(
      'How does it handle auth?',
      [
        { role: 'user', content: 'What does this repo do?' },
        { role: 'assistant', content: "It's a FastAPI backend." },
      ],
      expect.anything()
    );
  });

  it('excludes pending and errored messages from the history payload', async () => {
    useChatStore.setState({
      messages: [
        { id: '1', role: 'user', content: 'First question', timestamp: new Date(), status: 'complete' },
        { id: '2', role: 'assistant', content: '', timestamp: new Date(), status: 'error' },
      ],
      isLoading: false,
    });
    vi.mocked(queryStreamClient.query).mockResolvedValue({ answer: 'Answer.', sourceFiles: [], retrievedChunks: 0 });

    await useChatStore.getState().sendMessage('Second question');

    expect(queryStreamClient.query).toHaveBeenCalledWith(
      'Second question',
      [{ role: 'user', content: 'First question' }],
      expect.anything()
    );
  });

  it('retryMessage sends history from before the failed question, not including it', async () => {
    useChatStore.setState({
      messages: [
        { id: '1', role: 'user', content: 'What does this repo do?', timestamp: new Date(), status: 'complete' },
        { id: '2', role: 'assistant', content: "It's a FastAPI backend.", timestamp: new Date(), status: 'complete' },
        { id: '3', role: 'user', content: 'How does auth work?', timestamp: new Date(), status: 'complete' },
        {
          id: '4',
          role: 'assistant',
          content: 'Network down',
          timestamp: new Date(),
          status: 'error',
          question: 'How does auth work?',
        },
      ],
      isLoading: false,
    });
    vi.mocked(queryStreamClient.query).mockResolvedValue({ answer: 'It uses JWT.', sourceFiles: [], retrievedChunks: 0 });

    await useChatStore.getState().retryMessage('4');

    expect(queryStreamClient.query).toHaveBeenCalledWith(
      'How does auth work?',
      [
        { role: 'user', content: 'What does this repo do?' },
        { role: 'assistant', content: "It's a FastAPI backend." },
      ],
      expect.anything()
    );
  });

  it('falls back to the REST endpoint when the websocket stream fails', async () => {
    vi.mocked(queryStreamClient.query).mockRejectedValue(new Error('Failed to connect to the assistant.'));
    vi.mocked(queryService.queryRepository).mockResolvedValue({
      answer: 'Auth uses JWT.',
      source_files: ['src/auth.py'],
      retrieved_chunks: 2,
    });

    await useChatStore.getState().sendMessage('How does auth work?');

    const { messages, isLoading } = useChatStore.getState();
    expect(isLoading).toBe(false);
    expect(messages[1]).toMatchObject({
      status: 'complete',
      content: 'Auth uses JWT.',
      sourceFiles: ['src/auth.py'],
      retrievedChunks: 2,
    });
    expect(queryService.queryRepository).toHaveBeenCalledWith('How does auth work?', []);
  });

  it('marks the assistant message as errored when both the stream and the REST fallback fail', async () => {
    vi.mocked(queryStreamClient.query).mockRejectedValue(new Error('Connection to the assistant was lost.'));
    vi.mocked(queryService.queryRepository).mockRejectedValue(new Error('Network down'));

    await useChatStore.getState().sendMessage('How does auth work?');

    const { messages, isLoading } = useChatStore.getState();
    expect(isLoading).toBe(false);
    expect(messages[1]).toMatchObject({ status: 'error', content: 'Network down' });
  });

  it('ignores empty or whitespace-only questions', async () => {
    await useChatStore.getState().sendMessage('   ');

    expect(useChatStore.getState().messages).toHaveLength(0);
    expect(queryStreamClient.query).not.toHaveBeenCalled();
    expect(queryService.queryRepository).not.toHaveBeenCalled();
  });

  it('ignores new messages while a previous one is still loading', async () => {
    let resolveQuery: (value: { answer: string; sourceFiles: string[]; retrievedChunks: number }) => void = () => {};
    vi.mocked(queryStreamClient.query).mockReturnValue(
      new Promise((resolve) => {
        resolveQuery = resolve;
      })
    );

    const firstSend = useChatStore.getState().sendMessage('First question');
    await useChatStore.getState().sendMessage('Second question while loading');

    expect(queryStreamClient.query).toHaveBeenCalledTimes(1);
    expect(queryStreamClient.query).toHaveBeenCalledWith('First question', [], expect.anything());

    resolveQuery({ answer: 'Answer', sourceFiles: [], retrievedChunks: 0 });
    await firstSend;
  });

  it('clearChat resets messages and loading state', () => {
    useChatStore.setState({
      messages: [{ id: '1', role: 'user', content: 'hi', timestamp: new Date(), status: 'complete' }],
      isLoading: true,
    });

    useChatStore.getState().clearChat();

    expect(useChatStore.getState()).toMatchObject({ messages: [], isLoading: false });
  });
});
