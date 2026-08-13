'use client';

import { useChatStore } from '../store/useChatStore';
import { ChatHeader } from './ChatHeader';
import { MessageList } from './MessageList';
import { ChatInput } from './ChatInput';

interface ChatWindowProps {
  suggestedQuestions?: string[];
}

/**
 * Self-contained chat UI backed by useChatStore. Only depends on the chat
 * feature's own store/services, so it can be dropped onto any page.
 */
export function ChatWindow({ suggestedQuestions = [] }: ChatWindowProps) {
  const messages = useChatStore((state) => state.messages);
  const isLoading = useChatStore((state) => state.isLoading);
  const sendMessage = useChatStore((state) => state.sendMessage);
  const retryMessage = useChatStore((state) => state.retryMessage);
  const clearChat = useChatStore((state) => state.clearChat);

  return (
    <div className="flex h-[calc(100vh-160px)] min-h-[420px] flex-col overflow-hidden rounded-2xl border border-zinc-800 bg-zinc-900/40">
      <ChatHeader hasMessages={messages.length > 0} onClear={clearChat} />
      <MessageList
        messages={messages}
        suggestedQuestions={suggestedQuestions}
        onSuggestionClick={sendMessage}
        onRetry={retryMessage}
      />
      <ChatInput onSend={sendMessage} disabled={isLoading} />
    </div>
  );
}
