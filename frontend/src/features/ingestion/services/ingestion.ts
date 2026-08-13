import { BaseService } from '@/services/base-service';
import { IngestRequest, IngestResponse } from '@/types/api';

export class IngestionService extends BaseService {
  private static instance: IngestionService;

  private constructor() {
    super();
  }

  public static getInstance(): IngestionService {
    if (!IngestionService.instance) {
      IngestionService.instance = new IngestionService();
    }
    return IngestionService.instance;
  }

  /**
   * Ingests and indexes a GitHub repository.
   * @param repoUrl The URL of the GitHub repository to ingest.
   */
  public async ingestRepository(repoUrl: string): Promise<IngestResponse> {
    const payload: IngestRequest = { repo_url: repoUrl };
    return this.post<IngestResponse>('/ingest', payload);
  }
}

export const ingestionService = IngestionService.getInstance();
