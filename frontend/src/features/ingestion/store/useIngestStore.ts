import { create } from 'zustand';
import { ingestionService } from '../services/ingestion';
import { getErrorMessage, normalizeIngestResponse } from '@/lib/runtime-safety';

interface IngestState {
  isIngesting: boolean;
  error: string | null;
  success: boolean;
  repository: string | null;
  filesProcessed: number;
  chunksCreated: number;
  repoUrl: string | null;
  ingestRepo: (repoUrl: string) => Promise<void>;
  reset: () => void;
}

export const useIngestStore = create<IngestState>((set) => ({
  isIngesting: false,
  error: null,
  success: false,
  repository: null,
  filesProcessed: 0,
  chunksCreated: 0,
  repoUrl: null,

  ingestRepo: async (repoUrl: string) => {
    set({ isIngesting: true, error: null, success: false });
    try {
      const response = normalizeIngestResponse(await ingestionService.ingestRepository(repoUrl));
      set({
        isIngesting: false,
        success: true,
        repository: response.repository,
        filesProcessed: response.files_processed,
        chunksCreated: response.chunks_created,
        repoUrl: response.repo_url || repoUrl,
      });
    } catch (err: unknown) {
      set({
        isIngesting: false,
        success: false,
        error: getErrorMessage(err, 'Failed to ingest repository'),
      });
      throw err;
    }
  },

  reset: () =>
    set({
      isIngesting: false,
      error: null,
      success: false,
      repository: null,
      filesProcessed: 0,
      chunksCreated: 0,
      repoUrl: null,
    }),
}));
