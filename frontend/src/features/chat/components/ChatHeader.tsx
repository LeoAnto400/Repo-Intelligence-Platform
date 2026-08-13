import { MessageSquare, Trash2 } from 'lucide-react';
import { Button } from '@/components/ui/button';

interface ChatHeaderProps {
  hasMessages: boolean;
  onClear: () => void;
}

export function ChatHeader({ hasMessages, onClear }: ChatHeaderProps) {
  return (
    <div className="flex items-center justify-between border-b border-zinc-800/60 px-4 py-3 md:px-6">
      <div className="flex items-center gap-2 text-sm font-medium text-zinc-100">
        <MessageSquare className="h-4 w-4 text-indigo-400" />
        Codebase Assistant
      </div>
      <Button
        variant="ghost"
        size="sm"
        onClick={onClear}
        disabled={!hasMessages}
        className="gap-1.5 text-xs text-zinc-400 hover:text-zinc-100 disabled:opacity-40"
      >
        <Trash2 className="h-3.5 w-3.5" />
        Clear
      </Button>
    </div>
  );
}
