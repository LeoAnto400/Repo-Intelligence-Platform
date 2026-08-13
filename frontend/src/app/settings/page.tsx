import { RepositoryManager } from '@/features/repo-metadata/components/RepositoryManager';

export default function SettingsPage() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-lg font-semibold text-zinc-100">Repository Management</h1>
        <p className="text-sm text-zinc-400">
          Activate, re-ingest, or permanently remove previously indexed repositories.
        </p>
      </div>
      <RepositoryManager />
    </div>
  );
}
