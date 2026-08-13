'use client';

import { FileCode2, GitCommit, Loader2, Minus, Plus, RotateCcw, Sparkles } from 'lucide-react';
import { useRepoStore } from '@/features/repo-metadata/store/useRepoStore';
import { useCommitSummaryStore } from '../store/useCommitSummaryStore';
import type { CommitMetadata } from '@/types/api';

function shortHash(hash: string): string {
  return hash ? hash.slice(0, 7) : 'unknown';
}

function firstLine(message: string): string {
  const line = (message || '').split('\n')[0].trim();
  return line || '(no commit message)';
}

function formatDate(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value || 'Unknown date';
  return new Intl.DateTimeFormat('en-US', { dateStyle: 'medium', timeStyle: 'short' }).format(date);
}

function CommitCard({ commit }: { commit: CommitMetadata }) {
  const hash = commit.hash || '';
  const entry = useCommitSummaryStore((state) => state.summaries[hash]);
  const summarizeCommit = useCommitSummaryStore((state) => state.summarizeCommit);
  const status = entry?.status;

  return (
    <div className="rounded-xl border border-zinc-800 bg-zinc-900/40 p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2 text-xs text-zinc-500">
            <GitCommit className="h-3.5 w-3.5 shrink-0" />
            <code className="text-indigo-300">{shortHash(hash)}</code>
            <span>&middot;</span>
            <span className="truncate">{commit.author || 'Unknown author'}</span>
            <span>&middot;</span>
            <span>{formatDate(commit.time)}</span>
          </div>
          <p className="mt-1.5 text-sm font-medium text-zinc-100">{firstLine(commit.message)}</p>
        </div>

        <div className="flex shrink-0 items-center gap-3 text-xs">
          <span className="inline-flex items-center gap-1 text-emerald-400">
            <Plus className="h-3 w-3" />
            {commit.additions ?? 0}
          </span>
          <span className="inline-flex items-center gap-1 text-rose-400">
            <Minus className="h-3 w-3" />
            {commit.deletions ?? 0}
          </span>
          <span className="inline-flex items-center gap-1 text-zinc-500">
            <FileCode2 className="h-3 w-3" />
            {commit.filesChanged ?? 0}
          </span>
        </div>
      </div>

      <div className="mt-3">
        {!status && (
          <button
            type="button"
            onClick={() => summarizeCommit(hash)}
            disabled={!hash}
            className="inline-flex items-center gap-1.5 rounded-lg border border-zinc-800 px-2.5 py-1.5 text-xs text-zinc-400 transition-colors hover:border-indigo-500/40 hover:text-indigo-300 disabled:cursor-not-allowed disabled:opacity-50"
          >
            <Sparkles className="h-3.5 w-3.5" />
            Summarize
          </button>
        )}

        {status === 'loading' && (
          <div className="inline-flex items-center gap-2 text-xs text-zinc-500">
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
            Generating summary...
          </div>
        )}

        {status === 'error' && (
          <button
            type="button"
            onClick={() => summarizeCommit(hash)}
            title={entry?.error}
            className="inline-flex items-center gap-1.5 text-xs text-rose-300 transition-colors hover:text-rose-200"
          >
            <RotateCcw className="h-3 w-3" />
            Failed to summarize commit &mdash; retry
          </button>
        )}

        {status === 'done' && entry?.summary && (
          <div className="rounded-lg border border-indigo-500/20 bg-indigo-500/5 p-3 text-xs leading-5 text-zinc-300">
            {entry.summary}
          </div>
        )}
      </div>
    </div>
  );
}

export function CommitsList() {
  const commits = useRepoStore((state) => state.commits);

  if (commits.length === 0) {
    return <p className="text-sm text-zinc-500">No commit history is available for this repository.</p>;
  }

  return (
    <div className="space-y-4">
      <p className="text-xs text-zinc-500">Showing the {commits.length} most recent commits.</p>
      <div className="space-y-3">
        {commits.map((commit, index) => (
          <CommitCard key={commit.hash || index} commit={commit} />
        ))}
      </div>
    </div>
  );
}
