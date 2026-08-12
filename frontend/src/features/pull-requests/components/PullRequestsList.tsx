'use client';

import { useMemo, useState } from 'react';
import { GitMerge, GitPullRequest, GitPullRequestClosed, Loader2, RotateCcw, Sparkles, Tag } from 'lucide-react';
import { useRepoStore } from '@/features/repo-metadata/store/useRepoStore';
import { usePullRequestSummaryStore } from '../store/usePullRequestSummaryStore';
import type { PullRequestMetadata } from '@/types/api';

type StatusFilter = 'all' | 'open' | 'closed' | 'merged';

const STATUS_FILTERS: { value: StatusFilter; label: string }[] = [
  { value: 'all', label: 'All' },
  { value: 'open', label: 'Open' },
  { value: 'merged', label: 'Merged' },
  { value: 'closed', label: 'Closed' },
];

function formatDate(value: string | null | undefined): string {
  if (!value) return 'Unknown date';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat('en-US', { dateStyle: 'medium', timeStyle: 'short' }).format(date);
}

function statusBadge(status: string) {
  switch (status) {
    case 'merged':
      return {
        icon: GitMerge,
        label: 'Merged',
        className: 'border-purple-500/20 bg-purple-500/10 text-purple-300',
      };
    case 'closed':
      return {
        icon: GitPullRequestClosed,
        label: 'Closed',
        className: 'border-rose-500/20 bg-rose-500/10 text-rose-300',
      };
    default:
      return {
        icon: GitPullRequest,
        label: 'Open',
        className: 'border-emerald-500/20 bg-emerald-500/10 text-emerald-300',
      };
  }
}

function PullRequestCard({ pullRequest }: { pullRequest: PullRequestMetadata }) {
  const number = pullRequest.number;
  const entry = usePullRequestSummaryStore((state) => state.summaries[number]);
  const summarizePullRequest = usePullRequestSummaryStore((state) => state.summarizePullRequest);
  const status = entry?.status;
  const badge = statusBadge(pullRequest.status);
  const BadgeIcon = badge.icon;

  return (
    <div className="rounded-xl border border-zinc-800 bg-zinc-900/40 p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2 text-xs text-zinc-500">
            <span
              className={`inline-flex items-center gap-1 rounded border px-1.5 py-0.5 text-[10px] font-semibold ${badge.className}`}
            >
              <BadgeIcon className="h-3 w-3" />
              {badge.label}
            </span>
            <code className="text-indigo-300">#{pullRequest.number}</code>
            <span>&middot;</span>
            <span className="truncate">{pullRequest.author || 'Unknown author'}</span>
            <span>&middot;</span>
            <span>{formatDate(pullRequest.created_at)}</span>
          </div>
          <p className="mt-1.5 text-sm font-medium text-zinc-100">{pullRequest.title || '(no title)'}</p>
          {pullRequest.labels && pullRequest.labels.length > 0 && (
            <div className="mt-2 flex flex-wrap items-center gap-1.5">
              <Tag className="h-3 w-3 text-zinc-600" />
              {pullRequest.labels.map((label) => (
                <span
                  key={label}
                  className="rounded border border-zinc-700/60 bg-zinc-800/60 px-1.5 py-0.5 text-[10px] text-zinc-400"
                >
                  {label}
                </span>
              ))}
            </div>
          )}
        </div>
      </div>

      <div className="mt-3">
        {!status && (
          <button
            type="button"
            onClick={() => summarizePullRequest(number)}
            disabled={!number}
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
            onClick={() => summarizePullRequest(number)}
            title={entry?.error}
            className="inline-flex items-center gap-1.5 text-xs text-rose-300 transition-colors hover:text-rose-200"
          >
            <RotateCcw className="h-3 w-3" />
            Failed to summarize pull request &mdash; retry
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

export function PullRequestsList() {
  const pullRequests = useRepoStore((state) => state.pullRequests);
  const [filter, setFilter] = useState<StatusFilter>('all');

  const counts = useMemo(() => {
    const result: Record<StatusFilter, number> = { all: pullRequests.length, open: 0, closed: 0, merged: 0 };
    for (const pr of pullRequests) {
      if (pr.status === 'open' || pr.status === 'closed' || pr.status === 'merged') {
        result[pr.status] += 1;
      }
    }
    return result;
  }, [pullRequests]);

  const filtered = useMemo(
    () => (filter === 'all' ? pullRequests : pullRequests.filter((pr) => pr.status === filter)),
    [pullRequests, filter]
  );

  if (pullRequests.length === 0) {
    return <p className="text-sm text-zinc-500">No pull requests are available for this repository.</p>;
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-1.5">
        {STATUS_FILTERS.map((item) => (
          <button
            key={item.value}
            type="button"
            onClick={() => setFilter(item.value)}
            className={`rounded-lg border px-2.5 py-1.5 text-xs font-medium transition-colors ${
              filter === item.value
                ? 'border-indigo-500/40 bg-indigo-500/10 text-indigo-300'
                : 'border-zinc-800 text-zinc-500 hover:border-zinc-700 hover:text-zinc-300'
            }`}
          >
            {item.label}
            <span className="ml-1.5 text-zinc-600">{counts[item.value]}</span>
          </button>
        ))}
      </div>

      {filtered.length === 0 ? (
        <p className="text-sm text-zinc-500">No {filter} pull requests.</p>
      ) : (
        <div className="space-y-3">
          {filtered.map((pullRequest) => (
            <PullRequestCard key={pullRequest.id ?? pullRequest.number} pullRequest={pullRequest} />
          ))}
        </div>
      )}
    </div>
  );
}
