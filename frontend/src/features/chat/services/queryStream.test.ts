import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

type Listener = (event: { data?: string }) => void;

class FakeWebSocket {
  static OPEN = 1;
  static CONNECTING = 0;
  static CLOSED = 3;
  static instances: FakeWebSocket[] = [];

  readyState = FakeWebSocket.CONNECTING;
  onopen: (() => void) | null = null;
  onerror: (() => void) | null = null;
  onclose: (() => void) | null = null;
  sent: string[] = [];
  private listeners: Record<string, Listener[]> = {};

  constructor(public url: string) {
    FakeWebSocket.instances.push(this);
  }

  addEventListener(type: string, cb: Listener) {
    (this.listeners[type] ||= []).push(cb);
  }

  removeEventListener(type: string, cb: Listener) {
    this.listeners[type] = (this.listeners[type] || []).filter((l) => l !== cb);
  }

  send(data: string) {
    this.sent.push(data);
  }

  close() {
    this.readyState = FakeWebSocket.CLOSED;
    this.onclose?.();
    this.listeners.close?.forEach((cb) => cb({}));
  }

  triggerOpen() {
    this.readyState = FakeWebSocket.OPEN;
    this.onopen?.();
  }

  triggerMessage(data: unknown) {
    this.listeners.message?.forEach((cb) => cb({ data: JSON.stringify(data) }));
  }
}

// query() awaits connect() before registering listeners/sending, and that
// await needs at least one real event-loop turn to settle (connect()'s
// promise chain includes a `.finally()`) - a plain microtask isn't enough.
const flush = () => new Promise((resolve) => setTimeout(resolve, 0));

describe('QueryStreamClient', () => {
  beforeEach(() => {
    FakeWebSocket.instances = [];
    vi.stubGlobal('WebSocket', FakeWebSocket);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.resetModules();
  });

  async function loadClient() {
    const { queryStreamClient } = await import('./queryStream');
    return queryStreamClient;
  }

  it('connects, sends the question, forwards tokens, and resolves on done', async () => {
    const client = await loadClient();
    const onToken = vi.fn();

    const resultPromise = client.query('How does auth work?', [], { onToken });
    const socket = FakeWebSocket.instances[0];
    socket.triggerOpen();
    await flush();

    expect(socket.sent).toEqual([JSON.stringify({ question: 'How does auth work?', history: [] })]);

    socket.triggerMessage({ type: 'retrieval', retrieved_chunks: 2 });
    socket.triggerMessage({ type: 'token', text: 'Auth ' });
    socket.triggerMessage({ type: 'token', text: 'uses JWT.' });
    socket.triggerMessage({
      type: 'done',
      answer: 'Auth uses JWT tokens.',
      source_files: ['src/auth.py'],
      chunk_count: 2,
    });

    const result = await resultPromise;

    expect(onToken.mock.calls).toEqual([['Auth '], ['uses JWT.']]);
    expect(result).toEqual({
      answer: 'Auth uses JWT tokens.',
      sourceFiles: ['src/auth.py'],
      retrievedChunks: 2,
    });
  });

  it('sends the provided conversation history alongside the question', async () => {
    const client = await loadClient();
    const history = [
      { role: 'user' as const, content: 'What does this repo do?' },
      { role: 'assistant' as const, content: "It's a FastAPI backend." },
    ];

    const resultPromise = client.query('How does auth work?', history, { onToken: vi.fn() });
    const socket = FakeWebSocket.instances[0];
    socket.triggerOpen();
    await flush();

    expect(socket.sent).toEqual([JSON.stringify({ question: 'How does auth work?', history })]);

    socket.triggerMessage({ type: 'done', answer: 'It uses JWT.', source_files: [], chunk_count: 0 });
    await resultPromise;
  });

  it('reuses an already-open socket for a second query', async () => {
    const client = await loadClient();

    const first = client.query('First question', [], { onToken: vi.fn() });
    FakeWebSocket.instances[0].triggerOpen();
    await flush();
    FakeWebSocket.instances[0].triggerMessage({ type: 'done', answer: 'a', source_files: [], chunk_count: 0 });
    await first;

    const second = client.query('Second question', [], { onToken: vi.fn() });
    await flush();
    expect(FakeWebSocket.instances).toHaveLength(1);
    FakeWebSocket.instances[0].triggerMessage({ type: 'done', answer: 'b', source_files: [], chunk_count: 0 });
    await second;
  });

  it('rejects with the detail from an error event', async () => {
    const client = await loadClient();
    const resultPromise = client.query('Broken question', [], { onToken: vi.fn() });
    const socket = FakeWebSocket.instances[0];
    socket.triggerOpen();
    await flush();

    socket.triggerMessage({ type: 'error', detail: 'No repository has been ingested yet.' });

    await expect(resultPromise).rejects.toThrow('No repository has been ingested yet.');
  });

  it('rejects when the socket closes before a done/error event', async () => {
    const client = await loadClient();
    const resultPromise = client.query('Dropped question', [], { onToken: vi.fn() });
    const socket = FakeWebSocket.instances[0];
    socket.triggerOpen();
    await flush();

    socket.close();

    await expect(resultPromise).rejects.toThrow('Connection to the assistant was lost.');
  });

  it('rejects when the socket errors before opening', async () => {
    const client = await loadClient();
    const resultPromise = client.query('Unreachable question', [], { onToken: vi.fn() });
    const socket = FakeWebSocket.instances[0];

    socket.onerror?.();

    await expect(resultPromise).rejects.toThrow('Failed to connect to the assistant.');
  });
});
