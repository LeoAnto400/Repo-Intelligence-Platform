'use client';

import Link from 'next/link';
import { useRepoStore } from '@/features/repo-metadata/store/useRepoStore';
import { CommitsList } from '@/features/commits/components/CommitsList';

export default function CommitsPage() {
  const repository = useRepoStore((state) => state.repository);

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

  return (
    <section className="space-y-6">
      <div>
        <p className="text-xs font-medium uppercase tracking-[0.18em] text-indigo-300">Commit history</p>
        <h1 className="mt-2 text-2xl font-semibold tracking-tight text-zinc-50">Commits</h1>
      </div>
      <CommitsList />
    </section>
  );
}
