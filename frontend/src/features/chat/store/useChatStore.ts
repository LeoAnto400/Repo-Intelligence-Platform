import { create, type StoreApi } from 'zustand';
import { queryService } from '../services/query';
import { queryStreamClient } from '../services/queryStream';
import { getErrorMessage, normalizeQueryResponse } from '@/lib/runtime-safety';
import type { ConversationMessage } from '@/types/api';

// Bounds how much prior conversation gets sent with each new question. The
// backend applies its own (smaller) cap when building the prompt; this just
// keeps the request payload itself from growing unbounded in a long chat.
const MAX_HISTORY_MESSAGES = 20;

export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: Date;
  sourceFiles?: string[];
  retrievedChunks?: number;
  /** Assistant messages only: lifecycle of the answer this bubble represents. */
  status?: 'pending' | 'error' | 'complete';
  /** Assistant messages only: the question that produced this bubble, kept for retry. */
  question?: string;
}

interface ChatState {
  messages: ChatMessage[];
  isLoading: boolean;
  sendMessage: (question: string) => Promise<void>;
  retryMessage: (assistantMessageId: string) => Promise<void>;
  clearChat: () => void;
}

function createId(): string {
  return Math.random().toString(36).substring(2, 10);
}

type SetState = StoreApi<ChatState>['setState'];

/** Only completed messages have reliable final content, so pending/errored
 * bubbles are excluded rather than sent as (possibly empty) history turns. */
function buildHistoryPayload(messages: ChatMessage[]): ConversationMessage[] {
  return messages
    .filter((message) => message.status === 'complete' && message.content.trim().length > 0)
    .slice(-MAX_HISTORY_MESSAGES)
    .map((message) => ({ role: message.role, content: message.content }));
}

function appendToken(assistantMessageId: string, text: string, set: SetState): void {
  set((state) => ({
    messages: state.messages.map((message) =>
      message.id === assistantMessageId ? { ...message, content: message.content + text } : message
    ),
  }));
}

function finalizeMessage(
  assistantMessageId: string,
  response: { answer: string; source_files: string[]; retrieved_chunks: number },
  set: SetState
): void {
  set((state) => ({
    isLoading: false,
    messages: state.messages.map((message) =>
      message.id === assistantMessageId
        ? {
            ...message,
            status: 'complete',
            content: response.answer,
            sourceFiles: response.source_files,
            retrievedChunks: response.retrieved_chunks,
            timestamp: new Date(),
          }
        : message
    ),
  }));
}

async function runQuery(
  assistantMessageId: string,
  question: string,
  set: SetState,
  history: ConversationMessage[]
): Promise<void> {
  try {
    const result = await queryStreamClient.query(question, history, {
      onToken: (text) => appendToken(assistantMessageId, text, set),
    });
    finalizeMessage(
      assistantMessageId,
      { answer: result.answer, source_files: result.sourceFiles, retrieved_chunks: result.retrievedChunks },
      set
    );
    return;
  } catch {
    // Streaming path unavailable (e.g. a proxy that blocks websocket
    // upgrades) - fall back to the blocking REST endpoint below rather than
    // surfacing what may just be a transport-level failure.
  }

  try {
    const response = normalizeQueryResponse(await queryService.queryRepository(question, history));
    finalizeMessage(assistantMessageId, response, set);
  } catch (err: unknown) {
    const errorMessage = getErrorMessage(err, 'Failed to get answer from assistant.');
    set((state) => ({
      isLoading: false,
      messages: state.messages.map((message) =>
        message.id === assistantMessageId ? { ...message, status: 'error', content: errorMessage } : message
      ),
    }));
  }
}

export const useChatStore = create<ChatState>((set, get) => ({
  messages: [],
  isLoading: false,

  sendMessage: async (question: string) => {
    const trimmed = question.trim();
    if (!trimmed || get().isLoading) return;

    const history = buildHistoryPayload(get().messages);

    const userMessage: ChatMessage = {
      id: createId(),
      role: 'user',
      content: trimmed,
      timestamp: new Date(),
      status: 'complete',
    };
    const assistantMessageId = createId();
    const pendingMessage: ChatMessage = {
      id: assistantMessageId,
      role: 'assistant',
      content: '',
      timestamp: new Date(),
      status: 'pending',
      question: trimmed,
    };

    set((state) => ({
      messages: [...state.messages, userMessage, pendingMessage],
      isLoading: true,
    }));

    await runQuery(assistantMessageId, trimmed, set, history);
  },

  retryMessage: async (assistantMessageId: string) => {
    const currentMessages = get().messages;
    const targetIndex = currentMessages.findIndex((message) => message.id === assistantMessageId);
    const target = currentMessages[targetIndex];
    if (!target?.question || get().isLoading) return;

    // Exclude the failed question/answer pair itself (index - 1 is the
    // paired user message being retried) so it isn't sent as history too.
    const history = buildHistoryPayload(currentMessages.slice(0, Math.max(0, targetIndex - 1)));

    set((state) => ({
      isLoading: true,
      messages: state.messages.map((message) =>
        message.id === assistantMessageId ? { ...message, status: 'pending', content: '' } : message
      ),
    }));

    await runQuery(assistantMessageId, target.question, set, history);
  },

  clearChat: () => set({ messages: [], isLoading: false }),
}));
