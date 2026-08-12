import { create } from 'zustand';
import { repositoryService } from '../services/repository';
import { CommitMetadata, PullRequestMetadata, RepositoryMetadata, RepositorySummary } from '@/types/api';
import {
  getErrorMessage,
  normalizeRepositoryContext,
  normalizeRepositorySummaries,
} from '@/lib/runtime-safety';

interface RepoState {
  repository: string | null;
  repoUrl: string | null;
  metadata: RepositoryMetadata | null;
  files: Array<Record<string, unknown>>;
  commits: Array<CommitMetadata>;
  pullRequests: Array<PullRequestMetadata>;
  isLoading: boolean;
  error: string | null;
  availableRepositories: RepositorySummary[];
  isLoadingAvailable: boolean;
  availableError: string | null;
  isSelecting: boolean;
  fetchContext: () => Promise<void>;
  fetchAvailableRepositories: () => Promise<void>;
  selectRepository: (repository: string) => Promise<void>;
  deleteRepository: (repository: string) => Promise<void>;
  deactivateRepository: () => Promise<void>;
  reset: () => void;
}

export const useRepoStore = create<RepoState>((set) => ({
  repository: null,
  repoUrl: null,
  metadata: null,
  files: [],
  commits: [],
  pullRequests: [],
  isLoading: false,
  error: null,
  availableRepositories: [],
  isLoadingAvailable: false,
  availableError: null,
  isSelecting: false,

  fetchContext: async () => {
    set({ isLoading: true, error: null });
    try {
      const response = normalizeRepositoryContext(await repositoryService.getRepositoryContext());
      set({
        repository: response.repository,
        repoUrl: response.repo_url,
        metadata: response.metadata,
        files: response.files,
        commits: response.commits,
        pullRequests: response.pull_requests,
        isLoading: false,
      });
    } catch (err: unknown) {
      set({
        isLoading: false,
        error: getErrorMessage(err, 'Failed to fetch repository context'),
      });
    }
  },

  fetchAvailableRepositories: async () => {
    set({ isLoadingAvailable: true, availableError: null });
    try {
      const repositories = normalizeRepositorySummaries(await repositoryService.listRepositories());
      set({ availableRepositories: repositories, isLoadingAvailable: false });
    } catch (err: unknown) {
      set({
        isLoadingAvailable: false,
        availableError: getErrorMessage(err, 'Failed to load previously ingested repositories'),
      });
    }
  },

  selectRepository: async (repository: string) => {
    set({ isSelecting: true, error: null });
    try {
      const response = normalizeRepositoryContext(await repositoryService.selectRepository(repository));
      set({
        repository: response.repository,
        repoUrl: response.repo_url,
        metadata: response.metadata,
        files: response.files,
        commits: response.commits,
        pullRequests: response.pull_requests,
        isSelecting: false,
      });
    } catch (err: unknown) {
      set({
        isSelecting: false,
        error: getErrorMessage(err, 'Failed to activate the selected repository'),
      });
      throw err;
    }
  },

  deleteRepository: async (repository: string) => {
    await repositoryService.deleteRepository(repository);
    set((state) => ({
      availableRepositories: state.availableRepositories.filter((item) => item.repository !== repository),
      ...(state.repository === repository
        ? { repository: null, repoUrl: null, metadata: null, files: [], commits: [], pullRequests: [] }
        : {}),
    }));
  },

  deactivateRepository: async () => {
    await repositoryService.deactivateRepository();
    set({
      repository: null,
      repoUrl: null,
      metadata: null,
      files: [],
      commits: [],
      pullRequests: [],
      error: null,
    });
  },

  reset: () =>
    set({
      repository: null,
      repoUrl: null,
      metadata: null,
      files: [],
      commits: [],
      pullRequests: [],
      isLoading: false,
      error: null,
    }),
}));


