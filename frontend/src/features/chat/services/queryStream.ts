import { API_WS_BASE_URL } from '@/lib/api-client';
import type { ConversationMessage } from '@/types/api';

interface StreamHandlers {
  onToken: (text: string) => void;
  onRetrieval?: (retrievedChunks: number) => void;
}

interface StreamResult {
  answer: string;
  sourceFiles: string[];
  retrievedChunks: number;
}

const CONNECT_TIMEOUT_MS = 8000;

function asString(value: unknown): string {
  return typeof value === 'string' ? value : '';
}

function asStringArray(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string') : [];
}

function asNumber(value: unknown): number {
  return typeof value === 'number' && Number.isFinite(value) ? value : 0;
}

/**
 * Client for the streaming WS /ws/query endpoint. Keeps a single websocket
 * connection open and reuses it across questions, matching the backend's
 * one-connection-many-questions loop; callers are expected to serialize
 * questions themselves (useChatStore already does via its isLoading gate).
 */
class QueryStreamClient {
  private socket: WebSocket | null = null;
  private connecting: Promise<WebSocket> | null = null;

  private connect(): Promise<WebSocket> {
    if (this.socket && this.socket.readyState === WebSocket.OPEN) {
      return Promise.resolve(this.socket);
    }
    if (this.connecting) return this.connecting;

    this.connecting = new Promise<WebSocket>((resolve, reject) => {
      const socket = new WebSocket(`${API_WS_BASE_URL}/ws/query`);
      const timeout = setTimeout(() => {
        socket.close();
        reject(new Error('Timed out connecting to the assistant.'));
      }, CONNECT_TIMEOUT_MS);

      socket.onopen = () => {
        clearTimeout(timeout);
        this.socket = socket;
        resolve(socket);
      };
      socket.onerror = () => {
        clearTimeout(timeout);
        reject(new Error('Failed to connect to the assistant.'));
      };
      socket.onclose = () => {
        if (this.socket === socket) this.socket = null;
      };
    }).finally(() => {
      this.connecting = null;
    });

    return this.connecting;
  }

  async query(
    question: string,
    history: ConversationMessage[],
    handlers: StreamHandlers
  ): Promise<StreamResult> {
    const socket = await this.connect();

    return new Promise<StreamResult>((resolve, reject) => {
      const cleanup = () => {
        socket.removeEventListener('message', handleMessage);
        socket.removeEventListener('close', handleClose);
      };

      const handleMessage = (event: MessageEvent) => {
        let data: Record<string, unknown>;
        try {
          data = JSON.parse(event.data);
        } catch {
          return;
        }

        switch (data.type) {
          case 'retrieval':
            handlers.onRetrieval?.(asNumber(data.retrieved_chunks));
            break;
          case 'token':
            if (typeof data.text === 'string' && data.text) handlers.onToken(data.text);
            break;
          case 'done':
            cleanup();
            resolve({
              answer: asString(data.answer),
              sourceFiles: asStringArray(data.source_files),
              retrievedChunks: asNumber(data.chunk_count),
            });
            break;
          case 'error':
            cleanup();
            reject(new Error(asString(data.detail) || 'The assistant returned an error.'));
            break;
        }
      };

      const handleClose = () => {
        cleanup();
        reject(new Error('Connection to the assistant was lost.'));
      };

      socket.addEventListener('message', handleMessage);
      socket.addEventListener('close', handleClose);
      socket.send(JSON.stringify({ question, history }));
    });
  }
}

export const queryStreamClient = new QueryStreamClient();
