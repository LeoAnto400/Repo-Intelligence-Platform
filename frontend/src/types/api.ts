export interface IngestRequest {
  repo_url: string;
}

export interface IngestResponse {
  status: string;
  repository: string;
  files_processed: number;
  chunks_created: number;
  repo_url?: string;
}

export interface ConversationMessage {
  role: 'user' | 'assistant';
  content: string;
}

export interface QueryRequest {
  question: string;
  history?: ConversationMessage[];
}

export interface QueryResponse {
  answer: string;
  source_files: string[];
  retrieved_chunks: number;
}

export interface CommitMetadata {
  hash: string;
  author: string;
  message: string;
  time: string;
  branch: string;
  filesChanged: number;
  additions: number;
  deletions: number;
  diff: string;
  [key: string]: unknown;
}

export interface CommitSummaryResponse {
  hash: string;
  summary: string;
}

export interface PullRequestMetadata {
  number: number;
  title: string;
  state: string;
  author: string;
  created_at: string;
  [key: string]: unknown;
}

export interface RepositoryMetadata {
  name?: string | null;
  full_name?: string | null;
  owner?: string | null;
  description?: string | null;
  stars?: number | null;
  forks?: number | null;
  default_branch?: string | null;
  primary_language?: string | null;
  updated_at?: string | null;
  last_updated?: string | null;
  summary?: string | null;
  ai_summary?: string | null;
  repository_summary?: string | null;
  technologies?: string[] | null;
  detected_technologies?: string[] | null;
  suggested_questions?: string[] | null;
  [key: string]: unknown;
}

export interface RepositorySummary {
  repository: string;
  repo_url: string | null;
  chunk_count: number;
}

export interface DeleteRepositoryResponse {
  repository: string;
  status: string;
}

export interface RepositoryContextResponse {
  repository: string;
  repo_url: string;
  metadata: RepositoryMetadata;
  files: Array<Record<string, unknown>>;
  commits: Array<CommitMetadata>;
  pull_requests: Array<PullRequestMetadata>;
}



