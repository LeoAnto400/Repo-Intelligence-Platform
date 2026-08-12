import { beforeEach, describe, expect, it, vi } from 'vitest';
import { useRepoStore } from './useRepoStore';
import { repositoryService } from '../services/repository';

vi.mock('../services/repository', () => ({
  repositoryService: {
    getRepositoryContext: vi.fn(),
    listRepositories: vi.fn(),
    selectRepository: vi.fn(),
    deleteRepository: vi.fn(),
    deactivateRepository: vi.fn(),
  },
}));

function seedState(overrides: Partial<ReturnType<typeof useRepoStore.getState>> = {}) {
  useRepoStore.setState({
    repository: null,
    repoUrl: null,
    metadata: null,
    files: [],
    commits: [],
    pullRequests: [],
    isLoading: false,
    error: null,
    availableRepositories: [
      { repository: 'demo', repo_url: 'https://github.com/example/demo', chunk_count: 5 },
      { repository: 'other-repo', repo_url: 'https://github.com/example/other', chunk_count: 3 },
    ],
    isLoadingAvailable: false,
    availableError: null,
    isSelecting: false,
    ...overrides,
  });
}

describe('useRepoStore.deleteRepository', () => {
  beforeEach(() => {
    seedState();
    vi.mocked(repositoryService.deleteRepository).mockReset();
  });

  it('removes the repository from availableRepositories on success', async () => {
    vi.mocked(repositoryService.deleteRepository).mockResolvedValue({ repository: 'demo', status: 'deleted' });

    await useRepoStore.getState().deleteRepository('demo');

    const { availableRepositories } = useRepoStore.getState();
    expect(availableRepositories.map((item) => item.repository)).toEqual(['other-repo']);
    expect(repositoryService.deleteRepository).toHaveBeenCalledWith('demo');
  });

  it('clears the active repository fields when the deleted repository was active', async () => {
    seedState({
      repository: 'demo',
      repoUrl: 'https://github.com/example/demo',
      metadata: { ai_summary: 'A demo repo.' },
      files: [{ path: 'src/main.py' }],
      commits: [{ hash: 'abc' } as never],
    });
    vi.mocked(repositoryService.deleteRepository).mockResolvedValue({ repository: 'demo', status: 'deleted' });

    await useRepoStore.getState().deleteRepository('demo');

    const state = useRepoStore.getState();
    expect(state.repository).toBeNull();
    expect(state.repoUrl).toBeNull();
    expect(state.metadata).toBeNull();
    expect(state.files).toEqual([]);
    expect(state.commits).toEqual([]);
  });

  it('leaves the active repository untouched when a different repository is deleted', async () => {
    seedState({ repository: 'other-repo', repoUrl: 'https://github.com/example/other' });
    vi.mocked(repositoryService.deleteRepository).mockResolvedValue({ repository: 'demo', status: 'deleted' });

    await useRepoStore.getState().deleteRepository('demo');

    const state = useRepoStore.getState();
    expect(state.repository).toBe('other-repo');
    expect(state.repoUrl).toBe('https://github.com/example/other');
  });

  it('leaves availableRepositories unchanged and rethrows when the service call fails', async () => {
    vi.mocked(repositoryService.deleteRepository).mockRejectedValue(new Error('Repository not found'));

    await expect(useRepoStore.getState().deleteRepository('demo')).rejects.toThrow('Repository not found');
    expect(useRepoStore.getState().availableRepositories).toHaveLength(2);
  });
});

describe('useRepoStore.deactivateRepository', () => {
  beforeEach(() => {
    seedState({
      repository: 'demo',
      repoUrl: 'https://github.com/example/demo',
      metadata: { ai_summary: 'A demo repo.' },
      files: [{ path: 'src/main.py' }],
      commits: [{ hash: 'abc' } as never],
    });
    vi.mocked(repositoryService.deactivateRepository).mockReset();
  });

  it('clears the active repository fields on success without touching availableRepositories', async () => {
    vi.mocked(repositoryService.deactivateRepository).mockResolvedValue(undefined);

    await useRepoStore.getState().deactivateRepository();

    const state = useRepoStore.getState();
    expect(state.repository).toBeNull();
    expect(state.repoUrl).toBeNull();
    expect(state.metadata).toBeNull();
    expect(state.files).toEqual([]);
    expect(state.commits).toEqual([]);
    expect(state.availableRepositories).toHaveLength(2);
  });

  it('leaves the active repository untouched and rethrows when the service call fails', async () => {
    vi.mocked(repositoryService.deactivateRepository).mockRejectedValue(new Error('Network Error'));

    await expect(useRepoStore.getState().deactivateRepository()).rejects.toThrow('Network Error');
    expect(useRepoStore.getState().repository).toBe('demo');
  });
});
