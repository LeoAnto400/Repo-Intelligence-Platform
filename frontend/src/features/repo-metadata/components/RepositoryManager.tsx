'use client';

import { useEffect, useState } from 'react';
import { AlertTriangle, Database, GitBranch, Loader2, RefreshCw, RotateCcw, Trash2 } from 'lucide-react';
import { useRepoStore } from '../store/useRepoStore';
import { useIngestStore } from '@/features/ingestion/store/useIngestStore';
import { Button } from '@/components/ui/button';
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

type BusyAction = 'activate' | 'reingest' | 'delete';

export function RepositoryManager() {
  const availableRepositories = useRepoStore((state) => state.availableRepositories);
  const isLoadingAvailable = useRepoStore((state) => state.isLoadingAvailable);
  const availableError = useRepoStore((state) => state.availableError);
  const activeRepository = useRepoStore((state) => state.repository);
  const fetchAvailableRepositories = useRepoStore((state) => state.fetchAvailableRepositories);
  const selectRepository = useRepoStore((state) => state.selectRepository);
  const deleteRepository = useRepoStore((state) => state.deleteRepository);
  const isSelecting = useRepoStore((state) => state.isSelecting);

  const ingestRepo = useIngestStore((state) => state.ingestRepo);
  const isIngesting = useIngestStore((state) => state.isIngesting);

  const [busyRepo, setBusyRepo] = useState<string | null>(null);
  const [busyAction, setBusyAction] = useState<BusyAction | null>(null);
  const [pendingDelete, setPendingDelete] = useState<string | null>(null);
  const [rowError, setRowError] = useState<{ repository: string; message: string } | null>(null);

  useEffect(() => {
    void fetchAvailableRepositories();
  }, [fetchAvailableRepositories]);

  const anyActionBusy = isSelecting || isIngesting;

  const handleActivate = async (repository: string) => {
    setRowError(null);
    setBusyRepo(repository);
    setBusyAction('activate');
    try {
      await selectRepository(repository);
    } catch (err) {
      setRowError({
        repository,
        message: err instanceof Error ? err.message : 'Failed to activate repository.',
      });
    } finally {
      setBusyRepo(null);
      setBusyAction(null);
    }
  };

  const handleReingest = async (item: RepositorySummary) => {
    if (!item.repo_url) return;
    setRowError(null);
    setBusyRepo(item.repository);
    setBusyAction('reingest');
    try {
      await ingestRepo(item.repo_url);
      await fetchAvailableRepositories();
    } catch (err) {
      setRowError({
        repository: item.repository,
        message: err instanceof Error ? err.message : 'Failed to re-ingest repository.',
      });
    } finally {
      setBusyRepo(null);
      setBusyAction(null);
    }
  };

  const handleDelete = async (repository: string) => {
    setRowError(null);
    setBusyRepo(repository);
    setBusyAction('delete');
    try {
      await deleteRepository(repository);
    } catch (err) {
      setRowError({
        repository,
        message: err instanceof Error ? err.message : 'Failed to delete repository.',
      });
    } finally {
      setBusyRepo(null);
      setBusyAction(null);
      setPendingDelete(null);
    }
  };

  if (isLoadingAvailable) {
    return (
      <div className="flex items-center justify-center gap-2 py-10 text-xs text-zinc-500">
        <Loader2 className="h-3.5 w-3.5 animate-spin" />
        Loading indexed repositories...
      </div>
    );
  }

  if (availableError) {
    return (
      <div className="flex items-center justify-between gap-3 rounded-xl border border-rose-500/20 bg-rose-500/5 px-4 py-3 text-sm text-rose-300">
        <span className="flex items-center gap-2">
          <AlertTriangle className="h-4 w-4 shrink-0" />
          {availableError}
        </span>
        <Button
          size="sm"
          variant="outline"
          className="shrink-0 gap-1.5 border-rose-500/30 text-rose-200 hover:bg-rose-500/10"
          onClick={() => void fetchAvailableRepositories()}
        >
          <RotateCcw className="h-3.5 w-3.5" />
          Retry
        </Button>
      </div>
    );
  }

  if (availableRepositories.length === 0) {
    return (
      <div className="rounded-xl border border-dashed border-zinc-800 bg-zinc-900/20 py-10 text-center text-sm text-zinc-500">
        No repositories have been ingested yet.
      </div>
    );
  }

  return (
    <div className="space-y-2">
      {availableRepositories.map((item) => {
        const rowBusy = busyRepo === item.repository;
        const isActive = activeRepository === item.repository;

        return (
          <div
            key={item.repository}
            className="flex flex-col gap-3 rounded-xl border border-zinc-800/80 bg-zinc-900/40 p-4 sm:flex-row sm:items-center sm:justify-between"
          >
            <div className="flex min-w-0 items-center gap-3">
              <GitBranch className="h-4 w-4 shrink-0 text-zinc-500" />
              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  <p className="truncate text-sm font-medium text-zinc-200">{displayName(item)}</p>
                  {isActive && (
                    <span className="shrink-0 rounded border border-emerald-500/20 bg-emerald-500/10 px-1.5 py-0.5 text-[10px] font-semibold text-emerald-400">
                      Active
                    </span>
                  )}
                </div>
                <p className="flex items-center gap-1 text-[11px] text-zinc-500">
                  <Database className="h-3 w-3" />
                  {item.chunk_count} chunks indexed
                </p>
                {rowError?.repository === item.repository && (
                  <p className="mt-1 text-xs text-rose-400">{rowError.message}</p>
                )}
              </div>
            </div>

            <div className="flex shrink-0 items-center gap-2 self-end sm:self-auto">
              {pendingDelete === item.repository ? (
                <>
                  <span className="text-xs text-zinc-400">Delete this repository?</span>
                  <Button
                    size="sm"
                    variant="destructive"
                    disabled={rowBusy}
                    onClick={() => handleDelete(item.repository)}
                  >
                    {rowBusy && busyAction === 'delete' ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : 'Confirm'}
                  </Button>
                  <Button size="sm" variant="ghost" disabled={rowBusy} onClick={() => setPendingDelete(null)}>
                    Cancel
                  </Button>
                </>
              ) : (
                <>
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={isActive || anyActionBusy}
                    onClick={() => handleActivate(item.repository)}
                  >
                    {rowBusy && busyAction === 'activate' ? (
                      <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    ) : isActive ? (
                      'Active'
                    ) : (
                      'Activate'
                    )}
                  </Button>
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={!item.repo_url || anyActionBusy}
                    onClick={() => handleReingest(item)}
                    title={item.repo_url ? undefined : 'No source URL recorded for this repository'}
                    className="gap-1.5"
                  >
                    {rowBusy && busyAction === 'reingest' ? (
                      <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    ) : (
                      <RefreshCw className="h-3.5 w-3.5" />
                    )}
                    Re-ingest
                  </Button>
                  <Button
                    size="icon-sm"
                    variant="destructive"
                    disabled={anyActionBusy}
                    onClick={() => setPendingDelete(item.repository)}
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </Button>
                </>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}
