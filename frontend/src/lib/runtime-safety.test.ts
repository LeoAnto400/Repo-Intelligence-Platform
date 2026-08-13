import { describe, expect, it } from 'vitest';
import {
  appendLogLines,
  getErrorMessage,
  normalizeIngestResponse,
  normalizeQueryResponse,
  normalizeRepositoryContext,
  normalizeRepositorySummaries,
} from './runtime-safety';

describe('getErrorMessage', () => {
  it('uses the Error message when present', () => {
    expect(getErrorMessage(new Error('boom'), 'fallback')).toBe('boom');
  });

  it('uses a string error directly', () => {
    expect(getErrorMessage('network down', 'fallback')).toBe('network down');
  });

  it('falls back for empty or non-error values', () => {
    expect(getErrorMessage(new Error('   '), 'fallback')).toBe('fallback');
    expect(getErrorMessage('   ', 'fallback')).toBe('fallback');
    expect(getErrorMessage(null, 'fallback')).toBe('fallback');
    expect(getErrorMessage(undefined, 'fallback')).toBe('fallback');
    expect(getErrorMessage({ weird: true }, 'fallback')).toBe('fallback');
  });
});

describe('appendLogLines', () => {
  it('appends only well-formed non-empty strings', () => {
    expect(appendLogLines(['first'], 'second', '', '   ', 42, null, 'third')).toEqual([
      'first',
      'second',
      'third',
    ]);
  });

  it('returns the original array unchanged when nothing valid is appended', () => {
    const current = ['first'];
    expect(appendLogLines(current, '', undefined, 7)).toBe(current);
  });
});

describe('normalizeRepositoryContext', () => {
  it('fills in defaults for a missing/malformed response', () => {
    expect(normalizeRepositoryContext(null)).toEqual({
      repository: '',
      repo_url: '',
      metadata: { technologies: [], detected_technologies: [], suggested_questions: [] },
      files: [],
      commits: [],
      pull_requests: [],
    });
  });

  it('passes through valid fields and sanitizes metadata arrays', () => {
    const result = normalizeRepositoryContext({
      repository: 'demo',
      repo_url: 'https://github.com/example/demo',
      metadata: { technologies: ['Python', 42, 'FastAPI'], ai_summary: 'A demo repo.' },
      files: [{ path: 'src/main.py' }, 'not-an-object'],
      commits: [{ hash: 'abc' }],
      pull_requests: [{ number: 1 }],
    });

    expect(result.repository).toBe('demo');
    expect(result.metadata.technologies).toEqual(['Python', 'FastAPI']);
    expect(result.metadata.ai_summary).toBe('A demo repo.');
    expect(result.files).toEqual([{ path: 'src/main.py' }]);
    expect(result.commits).toEqual([{ hash: 'abc' }]);
  });
});

describe('normalizeIngestResponse', () => {
  it('throws when the repository field is missing', () => {
    expect(() =>
      normalizeIngestResponse({ status: 'success', repository: '', files_processed: 1, chunks_created: 1 })
    ).toThrow('The server returned an invalid ingestion response.');
  });

  it('defaults missing numeric fields to 0', () => {
    const result = normalizeIngestResponse({
      status: 'success',
      repository: 'demo',
      files_processed: Number.NaN,
      chunks_created: Number.NaN,
    });
    expect(result.files_processed).toBe(0);
    expect(result.chunks_created).toBe(0);
  });
});

describe('normalizeRepositorySummaries', () => {
  it('returns an empty array for non-array input', () => {
    expect(normalizeRepositorySummaries(null)).toEqual([]);
    expect(normalizeRepositorySummaries('not-an-array')).toEqual([]);
  });

  it('drops entries without a repository name and defaults chunk_count', () => {
    const result = normalizeRepositorySummaries([
      { repository: 'demo', repo_url: 'https://github.com/example/demo', chunk_count: 5 },
      { repository: '', chunk_count: 3 },
      { repository: 'other' },
    ]);

    expect(result).toEqual([
      { repository: 'demo', repo_url: 'https://github.com/example/demo', chunk_count: 5 },
      { repository: 'other', repo_url: null, chunk_count: 0 },
    ]);
  });
});

describe('normalizeQueryResponse', () => {
  it('provides a fallback answer and sanitized arrays for a malformed response', () => {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const result = normalizeQueryResponse({ answer: '', source_files: ['a', 2, 'b'] } as any);

    expect(result.answer).toBe('The assistant did not return an answer.');
    expect(result.source_files).toEqual(['a', 'b']);
    expect(result.retrieved_chunks).toBe(0);
  });

  it('passes through a well-formed response', () => {
    const result = normalizeQueryResponse({
      answer: 'Auth uses JWT.',
      source_files: ['src/auth.py'],
      retrieved_chunks: 2,
    });

    expect(result).toEqual({
      answer: 'Auth uses JWT.',
      source_files: ['src/auth.py'],
      retrieved_chunks: 2,
    });
  });
});
