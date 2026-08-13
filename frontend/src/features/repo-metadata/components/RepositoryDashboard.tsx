'use client';

import { Bot, CalendarClock, Code2, GitBranch, GitFork, Lightbulb, Star, UserRound } from 'lucide-react';
import { useRepoStore } from '@/features/repo-metadata/store/useRepoStore';
import type { RepositoryMetadata } from '@/types/api';

const unavailable = 'Not available';

function asStringList(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string' && item.trim().length > 0) : [];
}

function asDisplayText(value: unknown): string {
  return typeof value === 'string' && value.trim() ? value : unavailable;
}

function formatCount(value: unknown): string {
  return typeof value === 'number' && Number.isFinite(value) ? new Intl.NumberFormat('en-US').format(value) : unavailable;
}

function formatDate(value: unknown): string {
  if (typeof value !== 'string' || !value.trim()) return unavailable;
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? value
    : new Intl.DateTimeFormat('en-US', { dateStyle: 'medium', timeZone: 'UTC' }).format(date);
}

function getAnalysisList(metadata: RepositoryMetadata, primaryKey: keyof RepositoryMetadata, secondaryKey: keyof RepositoryMetadata): string[] {
  const primary = asStringList(metadata[primaryKey]);
  return primary.length > 0 ? primary : asStringList(metadata[secondaryKey]);
}

function Metric({ icon: Icon, label, value }: { icon: React.ComponentType<{ className?: string }>; label: string; value: string }) {
  return <div className="rounded-xl border border-zinc-800 bg-zinc-900/45 p-4"><div className="flex items-center gap-2 text-xs text-zinc-500"><Icon className="h-3.5 w-3.5 text-indigo-400" />{label}</div><p className="mt-2 truncate text-lg font-semibold text-zinc-100">{value}</p></div>;
}

export function RepositoryDashboard() {
  const { repository, metadata, isLoading, error } = useRepoStore();
  if (isLoading && !metadata) return <p role="status" className="text-sm text-zinc-400">Loading repository metadata…</p>;
  if (error && !metadata) return <p role="alert" className="text-sm text-rose-400">{error}</p>;

  const data = metadata ?? {};
  const name = asDisplayText(data.name) !== unavailable ? asDisplayText(data.name) : asDisplayText(data.full_name) !== unavailable ? asDisplayText(data.full_name) : asDisplayText(repository);
  const summary = asDisplayText(data.ai_summary) !== unavailable ? data.ai_summary : asDisplayText(data.repository_summary) !== unavailable ? data.repository_summary : data.summary;
  const technologies = getAnalysisList(data, 'detected_technologies', 'technologies');
  const questions = asStringList(data.suggested_questions);
  const lastUpdated = data.updated_at ?? data.last_updated;

  return <section className="space-y-6">
    {error && <p role="alert" className="rounded-lg border border-rose-500/20 bg-rose-500/10 px-4 py-3 text-sm text-rose-300">{error}</p>}
    <div className="rounded-2xl border border-zinc-800 bg-gradient-to-br from-zinc-900 via-zinc-900/80 to-indigo-950/30 p-6 md:p-8">
      <p className="text-xs font-medium uppercase tracking-[0.18em] text-indigo-300">Repository dashboard</p>
      <h1 className="mt-3 text-3xl font-semibold tracking-tight text-zinc-50">{name}</h1>
      <div className="mt-4 flex flex-wrap gap-x-5 gap-y-2 text-sm text-zinc-400"><span className="inline-flex items-center gap-2"><UserRound className="h-4 w-4" />{asDisplayText(data.owner)}</span><span className="inline-flex items-center gap-2"><Code2 className="h-4 w-4" />{asDisplayText(data.primary_language)}</span><span className="inline-flex items-center gap-2"><CalendarClock className="h-4 w-4" />{formatDate(lastUpdated)}</span></div>
      <p className="mt-5 max-w-3xl text-sm leading-6 text-zinc-300">{asDisplayText(data.description)}</p>
    </div>
    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4"><Metric icon={Star} label="Stars" value={formatCount(data.stars)} /><Metric icon={GitFork} label="Forks" value={formatCount(data.forks)} /><Metric icon={GitBranch} label="Default branch" value={asDisplayText(data.default_branch)} /><Metric icon={Code2} label="Primary language" value={asDisplayText(data.primary_language)} /></div>
    <div className="grid gap-6 lg:grid-cols-5">
      <article className="rounded-2xl border border-indigo-500/20 bg-indigo-500/5 p-6 lg:col-span-3"><div className="flex items-center gap-2 text-sm font-medium text-indigo-200"><Bot className="h-4 w-4" />AI-generated repository summary</div><p className="mt-4 whitespace-pre-wrap text-sm leading-6 text-zinc-300">{asDisplayText(summary)}</p></article>
      <article className="rounded-2xl border border-zinc-800 bg-zinc-900/45 p-6 lg:col-span-2"><h2 className="flex items-center gap-2 text-sm font-medium text-zinc-100"><Code2 className="h-4 w-4 text-emerald-400" />Detected technologies</h2>{technologies.length > 0 ? <div className="mt-4 flex flex-wrap gap-2">{technologies.map((technology) => <span key={technology} className="rounded-full border border-emerald-500/20 bg-emerald-500/10 px-2.5 py-1 text-xs text-emerald-200">{technology}</span>)}</div> : <p className="mt-4 text-sm text-zinc-500">{unavailable}</p>}</article>
    </div>
    <article className="rounded-2xl border border-zinc-800 bg-zinc-900/45 p-6"><h2 className="flex items-center gap-2 text-sm font-medium text-zinc-100"><Lightbulb className="h-4 w-4 text-amber-400" />Suggested questions</h2>{questions.length > 0 ? <ul className="mt-4 grid gap-2 md:grid-cols-2">{questions.map((question) => <li key={question} className="rounded-lg border border-zinc-800 bg-zinc-950/50 px-3 py-2.5 text-sm text-zinc-300">{question}</li>)}</ul> : <p className="mt-4 text-sm text-zinc-500">{unavailable}</p>}</article>
  </section>;
}