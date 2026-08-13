import { BaseService } from '@/services/base-service';
import { CommitSummaryResponse } from '@/types/api';

export class CommitsService extends BaseService {
  private static instance: CommitsService;

  private constructor() {
    super();
  }

  public static getInstance(): CommitsService {
    if (!CommitsService.instance) {
      CommitsService.instance = new CommitsService();
    }
    return CommitsService.instance;
  }

  /**
   * Requests an AI-generated summary of a single commit in the active repository.
   */
  public async summarizeCommit(hash: string): Promise<CommitSummaryResponse> {
    return this.post<CommitSummaryResponse>(`/commits/${encodeURIComponent(hash)}/summary`);
  }
}

export const commitsService = CommitsService.getInstance();
