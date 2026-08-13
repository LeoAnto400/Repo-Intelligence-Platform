import type {
  IngestResponse,
  QueryResponse,
  RepositoryContextResponse,
  RepositoryMetadata,
  RepositorySummary,
} from '@/types/api';

export function getErrorMessage(error: unknown, fallback: string): string {
  if (error instanceof Error && error.message.trim()) return error.message;
  if (typeof error === 'string' && error.trim()) return error;
  return fallback;
}

function asString(value: unknown): string | null {
  return typeof value === 'string' && value.trim() ? value : null;
}

function asStringArray(value: unknown): string[] {
  return Array.isArray(value)
    ? value.filter((item): item is string => typeof item === 'string' && item.trim().length > 0)
    : [];
}

/** Appends only well-formed, non-empty string lines to a log array, dropping anything malformed. */
export function appendLogLines(current: string[], ...lines: unknown[]): string[] {
  const sanitized = lines.filter((line): line is string => typeof line === 'string' && line.trim().length > 0);
  return sanitized.length ? [...current, ...sanitized] : current;
}

export function normalizeRepositoryContext(value: unknown): RepositoryContextResponse {
  const response = value && typeof value === 'object' ? value as Partial<RepositoryContextResponse> : {};
  const metadata = response.metadata && typeof response.metadata === 'object'
    ? response.metadata as RepositoryMetadata
    : {};

  return {
    repository: asString(response.repository) ?? '',
    repo_url: asString(response.repo_url) ?? '',
    metadata: {
      ...metadata,
      technologies: asStringArray(metadata.technologies),
      detected_technologies: asStringArray(metadata.detected_technologies),
      suggested_questions: asStringArray(metadata.suggested_questions),
    },
    files: Array.isArray(response.files) ? response.files.filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === 'object' && !Array.isArray(item)) : [],
    commits: Array.isArray(response.commits) ? response.commits : [],
    pull_requests: Array.isArray(response.pull_requests) ? response.pull_requests : [],
  };
}

export function normalizeIngestResponse(value: IngestResponse): IngestResponse {
  if (!asString(value?.repository)) throw new Error('The server returned an invalid ingestion response.');
  return {
    status: asString(value.status) ?? 'success',
    repository: value.repository,
    files_processed: Number.isFinite(value.files_processed) ? value.files_processed : 0,
    chunks_created: Number.isFinite(value.chunks_created) ? value.chunks_created : 0,
    repo_url: asString(value.repo_url) ?? undefined,
  };
}

export function normalizeRepositorySummaries(value: unknown): RepositorySummary[] {
  if (!Array.isArray(value)) return [];
  return value
    .filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === 'object')
    .map((item) => ({
      repository: asString(item.repository) ?? '',
      repo_url: asString(item.repo_url),
      chunk_count: typeof item.chunk_count === 'number' && Number.isFinite(item.chunk_count) ? item.chunk_count : 0,
    }))
    .filter((item) => item.repository.length > 0);
}

export function normalizeQueryResponse(value: QueryResponse): QueryResponse {
  return {
    answer: asString(value?.answer) ?? 'The assistant did not return an answer.',
    source_files: asStringArray(value?.source_files),
    retrieved_chunks: Number.isFinite(value?.retrieved_chunks) ? value.retrieved_chunks : 0,
  };
}