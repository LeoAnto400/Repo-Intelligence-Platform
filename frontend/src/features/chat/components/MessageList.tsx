'use client';

import { useEffect, useRef } from 'react';
import { Sparkles } from 'lucide-react';
import type { ChatMessage } from '../store/useChatStore';
import { MessageBubble } from './MessageBubble';

interface MessageListProps {
  messages: ChatMessage[];
  suggestedQuestions?: string[];
  onSuggestionClick: (question: string) => void;
  onRetry: (assistantMessageId: string) => void;
}

export function MessageList({ messages, suggestedQuestions = [], onSuggestionClick, onRetry }: MessageListProps) {
  const bottomRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' });
  }, [messages]);

  if (messages.length === 0) {
    return (
      <div className="flex flex-1 flex-col items-center justify-center gap-4 overflow-y-auto px-6 text-center">
        <div className="flex h-12 w-12 items-center justify-center rounded-full border border-indigo-500/20 bg-indigo-500/10 text-indigo-400">
          <Sparkles className="h-5 w-5" />
        </div>
        <div>
          <p className="text-sm font-medium text-zinc-200">Ask anything about this codebase</p>
          <p className="mt-1 text-xs text-zinc-500">Answers are grounded in the ingested repository source.</p>
        </div>
        {suggestedQuestions.length > 0 && (
          <div className="flex max-w-lg flex-wrap justify-center gap-2 pt-2">
            {suggestedQuestions.map((question) => (
              <button
                key={question}
                onClick={() => onSuggestionClick(question)}
                className="rounded-lg border border-zinc-800 bg-zinc-950/50 px-3 py-2 text-xs text-zinc-300 transition-colors hover:border-indigo-500/40 hover:text-indigo-200"
              >
                {question}
              </button>
            ))}
          </div>
        )}
      </div>
    );
  }

  return (
    <div className="flex-1 space-y-4 overflow-y-auto px-4 py-4 md:px-6">
      {messages.map((message) => (
        <MessageBubble key={message.id} message={message} onRetry={onRetry} />
      ))}
      <div ref={bottomRef} />
    </div>
  );
}
