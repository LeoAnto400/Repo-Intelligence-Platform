import { BaseService } from '@/services/base-service';
import { ConversationMessage, QueryRequest, QueryResponse } from '@/types/api';

export class QueryService extends BaseService {
  private static instance: QueryService;

  private constructor() {
    super();
  }

  public static getInstance(): QueryService {
    if (!QueryService.instance) {
      QueryService.instance = new QueryService();
    }
    return QueryService.instance;
  }

  /**
   * Queries the active ingested repository.
   * @param question The question regarding the codebase.
   * @param history Prior conversation turns, most recent last, so the
   *   assistant can resolve references like "it" in the new question.
   */
  public async queryRepository(question: string, history: ConversationMessage[] = []): Promise<QueryResponse> {
    const payload: QueryRequest = { question, history };
    return this.post<QueryResponse>('/query', payload);
  }
}

export const queryService = QueryService.getInstance();
