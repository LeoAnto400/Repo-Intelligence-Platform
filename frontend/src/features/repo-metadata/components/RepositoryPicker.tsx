'use client';

import { useEffect, useState } from 'react';
import { motion } from 'framer-motion';
import { AlertTriangle, Database, GitBranch, Loader2, RotateCcw } from 'lucide-react';
import { useRepoStore } from '../store/useRepoStore';
import type { RepositorySummary } from '@/types/api';

function displayName(item: RepositorySummary): string {
  if (!item.repo_url) return item.repository;
  try {
    const path = new URL(item.repo_url).pathname.replace(/^\/|\/$/g, '');
    return path || item.repository;
  } catch {
    return item.repository;
  }
}

export function RepositoryPicker() {
  const availableRepositories = useRepoStore((state) => state.availableRepositories);
  const isLoadingAvailable = useRepoStore((state) => state.isLoadingAvailable);
  const availableError = useRepoStore((state) => state.availableError);
  const isSelecting = useRepoStore((state) => state.isSelecting);
  const fetchAvailableRepositories = useRepoStore((state) => state.fetchAvailableRepositories);
  const selectRepository = useRepoStore((state) => state.selectRepository);
  const [selectingName, setSelectingName] = useState<string | null>(null);
  const [selectError, setSelectError] = useState('');

  useEffect(() => {
    void fetchAvailableRepositories();
  }, [fetchAvailableRepositories]);

  const handleSelect = async (repository: string) => {
    setSelectError('');
    setSelectingName(repository);
    try {
      await selectRepository(repository);
    } catch (err: unknown) {
      setSelectError(err instanceof Error ? err.message : 'Failed to activate the selected repository.');
    } finally {
      setSelectingName(null);
    }
  };

  if (isLoadingAvailable) {
    return (
      <div className="flex items-center justify-center gap-2 py-6 text-xs text-zinc-500">
        <Loader2 className="h-3.5 w-3.5 animate-spin" />
        Checking for previously indexed repositories...
      </div>
    );
  }

  if (availableError) {
    return (
      <div className="mx-auto flex w-full max-w-2xl items-center justify-between gap-3 rounded-xl border border-rose-500/20 bg-rose-500/5 px-4 py-3 text-left text-xs text-rose-300">
        <span className="flex items-center gap-2">
          <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
          Couldn&apos;t check for previously indexed repositories: {availableError}
        </span>
        <button
          type="button"
          onClick={() => void fetchAvailableRepositories()}
          className="inline-flex shrink-0 items-center gap-1.5 rounded-lg border border-rose-500/30 px-2.5 py-1.5 font-medium text-rose-200 transition-colors hover:bg-rose-500/10"
        >
          <RotateCcw className="h-3.5 w-3.5" />
          Retry
        </button>
      </div>
    );
  }

  if (availableRepositories.length === 0) {
    return null;
  }

  return (
    <motion.div
      initial={{ opacity: 0, y: -8 }}
      animate={{ opacity: 1, y: 0 }}
      className="mx-auto w-full max-w-2xl space-y-3 text-left"
    >
      <div className="flex items-center gap-2 text-xs font-medium uppercase tracking-wider text-zinc-500">
        <Database className="h-3.5 w-3.5 text-indigo-400" />
        Already indexed &mdash; select one instead of re-ingesting
      </div>

      <div className="grid gap-2 sm:grid-cols-2">
        {availableRepositories.map((item) => {
          const isBusy = isSelecting && selectingName === item.repository;
          return (
            <button
              key={item.repository}
              type="button"
              onClick={() => handleSelect(item.repository)}
              disabled={isSelecting}
              className="group flex items-center justify-between gap-3 rounded-xl border border-zinc-800/80 bg-zinc-900/40 px-4 py-3 text-left transition-colors hover:border-indigo-500/40 hover:bg-zinc-900/70 disabled:cursor-not-allowed disabled:opacity-50"
            >
              <div className="flex min-w-0 items-center gap-2.5">
                <GitBranch className="h-4 w-4 shrink-0 text-zinc-500 group-hover:text-indigo-400" />
                <div className="min-w-0">
                  <p className="truncate text-sm font-medium text-zinc-200">{displayName(item)}</p>
                  <p className="text-[11px] text-zinc-500">{item.chunk_count} chunks indexed</p>
                </div>
              </div>
              {isBusy && <Loader2 className="h-4 w-4 shrink-0 animate-spin text-indigo-400" />}
            </button>
          );
        })}
      </div>

      {selectError && <p className="text-xs text-rose-400">{selectError}</p>}
    </motion.div>
  );
}
