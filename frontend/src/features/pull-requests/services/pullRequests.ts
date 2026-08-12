import { BaseService } from '@/services/base-service';
import { PullRequestSummaryResponse } from '@/types/api';

export class PullRequestsService extends BaseService {
  private static instance: PullRequestsService;

  private constructor() {
    super();
  }

  public static getInstance(): PullRequestsService {
    if (!PullRequestsService.instance) {
      PullRequestsService.instance = new PullRequestsService();
    }
    return PullRequestsService.instance;
  }

  /**
   * Requests an AI-generated summary of a single pull request in the active repository.
   */
  public async summarizePullRequest(number: number): Promise<PullRequestSummaryResponse> {
    return this.post<PullRequestSummaryResponse>(`/pull-requests/${number}/summary`);
  }
}

export const pullRequestsService = PullRequestsService.getInstance();
