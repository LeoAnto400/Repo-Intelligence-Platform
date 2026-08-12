import { create } from 'zustand';
import { pullRequestsService } from '../services/pullRequests';
import { getErrorMessage } from '@/lib/runtime-safety';

interface PullRequestSummaryEntry {
  status: 'loading' | 'error' | 'done';
  summary?: string;
  error?: string;
}

interface PullRequestSummaryState {
  summaries: Record<number, PullRequestSummaryEntry>;
  summarizePullRequest: (number: number) => Promise<void>;
}

export const usePullRequestSummaryStore = create<PullRequestSummaryState>((set, get) => ({
  summaries: {},

  summarizePullRequest: async (number: number) => {
    if (!number || get().summaries[number]?.status === 'loading') return;

    set((state) => ({ summaries: { ...state.summaries, [number]: { status: 'loading' } } }));

    try {
      const response = await pullRequestsService.summarizePullRequest(number);
      set((state) => ({
        summaries: { ...state.summaries, [number]: { status: 'done', summary: response.summary } },
      }));
    } catch (err: unknown) {
      set((state) => ({
        summaries: {
          ...state.summaries,
          [number]: { status: 'error', error: getErrorMessage(err, 'Failed to summarize pull request') },
        },
      }));
    }
  },
}));
