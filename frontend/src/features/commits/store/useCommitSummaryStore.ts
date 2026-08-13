import { create } from 'zustand';
import { commitsService } from '../services/commits';
import { getErrorMessage } from '@/lib/runtime-safety';

interface CommitSummaryEntry {
  status: 'loading' | 'error' | 'done';
  summary?: string;
  error?: string;
}

interface CommitSummaryState {
  summaries: Record<string, CommitSummaryEntry>;
  summarizeCommit: (hash: string) => Promise<void>;
}

export const useCommitSummaryStore = create<CommitSummaryState>((set, get) => ({
  summaries: {},

  summarizeCommit: async (hash: string) => {
    if (!hash || get().summaries[hash]?.status === 'loading') return;

    set((state) => ({ summaries: { ...state.summaries, [hash]: { status: 'loading' } } }));

    try {
      const response = await commitsService.summarizeCommit(hash);
      set((state) => ({
        summaries: { ...state.summaries, [hash]: { status: 'done', summary: response.summary } },
      }));
    } catch (err: unknown) {
      set((state) => ({
        summaries: {
          ...state.summaries,
          [hash]: { status: 'error', error: getErrorMessage(err, 'Failed to summarize commit') },
        },
      }));
    }
  },
}));
