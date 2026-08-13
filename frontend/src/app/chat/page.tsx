'use client';

import Link from 'next/link';
import { ChatWindow } from '@/features/chat/components/ChatWindow';
import { useRepoStore } from '@/features/repo-metadata/store/useRepoStore';

export default function ChatPage() {
  const repository = useRepoStore((state) => state.repository);
  const metadata = useRepoStore((state) => state.metadata);
  const suggestedQuestions = metadata?.suggested_questions ?? [];

  if (!repository) {
    return (
      <div className="flex h-[60vh] flex-col items-center justify-center gap-3 text-center">
        <p className="text-sm text-zinc-400">No repository has been ingested yet.</p>
        <Link href="/" className="text-sm text-indigo-400 underline hover:text-indigo-300">
          Go ingest a repository
        </Link>
      </div>
    );
  }

  return <ChatWindow suggestedQuestions={suggestedQuestions} />;
}
