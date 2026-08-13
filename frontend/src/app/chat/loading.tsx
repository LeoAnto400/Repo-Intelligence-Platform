import { Loader2 } from 'lucide-react';

export default function ChatLoading() {
  return (
    <div className="flex min-h-[60vh] flex-col items-center justify-center gap-3 text-zinc-500">
      <Loader2 className="h-5 w-5 animate-spin text-indigo-400" />
      <p className="text-xs">Loading chat...</p>
    </div>
  );
}
