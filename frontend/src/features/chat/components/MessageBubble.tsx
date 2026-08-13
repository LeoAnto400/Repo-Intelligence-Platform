import { Bot, RotateCcw, User } from 'lucide-react';
import { cn } from '@/lib/utils';
import type { ChatMessage } from '../store/useChatStore';
import { MarkdownRenderer } from './MarkdownRenderer';
import { SourceCitations } from './SourceCitations';
import { TypingIndicator } from './TypingIndicator';

interface MessageBubbleProps {
  message: ChatMessage;
  onRetry: (assistantMessageId: string) => void;
}

function formatTimestamp(date: Date): string {
  return new Intl.DateTimeFormat('en-US', { hour: 'numeric', minute: '2-digit' }).format(date);
}

export function MessageBubble({ message, onRetry }: MessageBubbleProps) {
  const isUser = message.role === 'user';
  const isError = message.status === 'error';
  const isPending = message.status === 'pending';

  return (
    <div className={cn('flex gap-3', isUser ? 'flex-row-reverse' : 'flex-row')}>
      <div
        className={cn(
          'flex h-7 w-7 shrink-0 items-center justify-center rounded-full border',
          isUser ? 'border-zinc-700 bg-zinc-800 text-zinc-300' : 'border-indigo-500/30 bg-indigo-500/10 text-indigo-400'
        )}
      >
        {isUser ? <User className="h-3.5 w-3.5" /> : <Bot className="h-3.5 w-3.5" />}
      </div>

      <div className={cn('flex min-w-0 max-w-[80%] flex-col gap-1.5', isUser ? 'items-end' : 'items-start')}>
        <div
          className={cn(
            'min-w-0 rounded-2xl px-4 py-2.5',
            isUser
              ? 'bg-indigo-600 text-sm leading-6 text-white'
              : isError
                ? 'border border-rose-500/30 bg-rose-500/10 text-sm leading-6 text-rose-200'
                : 'border border-zinc-800 bg-zinc-900/60 text-zinc-100'
          )}
        >
          {isPending && !message.content ? (
            <TypingIndicator />
          ) : isUser ? (
            <p className="whitespace-pre-wrap">{message.content}</p>
          ) : (
            <MarkdownRenderer content={message.content} />
          )}
        </div>

        {isError && (
          <button
            onClick={() => onRetry(message.id)}
            className="inline-flex items-center gap-1.5 text-xs text-rose-300 transition-colors hover:text-rose-200"
          >
            <RotateCcw className="h-3 w-3" />
            Retry
          </button>
        )}

        {!isUser && !isPending && !isError && message.sourceFiles && message.sourceFiles.length > 0 && (
          <SourceCitations files={message.sourceFiles} retrievedChunks={message.retrievedChunks} />
        )}

        {!isPending && <span className="px-1 text-[10px] text-zinc-600">{formatTimestamp(message.timestamp)}</span>}
      </div>
    </div>
  );
}
