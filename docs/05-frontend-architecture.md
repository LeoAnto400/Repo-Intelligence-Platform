# 05 — Frontend: Architecture

The frontend is a **Next.js 15 App Router** application. It talks to the FastAPI backend
directly over REST + WebSocket (no server-side proxying), and organizes application code by
**feature**, each with its own `components/`, `services/`, and `store/`.

## Directory structure

```
frontend/src/
├── app/                        # Next.js App Router — one folder per route
│   ├── layout.tsx              # Root layout: fonts, <Providers>, <DashboardShell>
│   ├── providers.tsx           # 'use client' — QueryClientProvider (TanStack Query)
│   ├── page.tsx                # "/" — landing page or RepositoryDashboard
│   ├── error.tsx                # Route-level error boundary
│   ├── not-found.tsx            # 404 page
│   ├── loading.tsx              # Root loading fallback
│   ├── chat/{page.tsx, loading.tsx}
│   ├── commits/{page.tsx, loading.tsx}
│   └── settings/{page.tsx, loading.tsx}
├── components/
│   ├── DashboardShell.tsx      # Sidebar + top bar shell, conditional on active repo
│   └── ui/button.tsx           # shadcn-generated Button (cva variants)
├── features/
│   ├── ingestion/{components/IngestPanel.tsx, services/ingestion.ts, store/useIngestStore.ts}
│   ├── repo-metadata/{components/{RepositoryDashboard,RepositoryManager,RepositoryPicker}.tsx, services/repository.ts, store/useRepoStore.ts}
│   ├── chat/{components/{ChatWindow,ChatHeader,ChatInput,MessageList,MessageBubble,MarkdownRenderer,SourceCitations,TypingIndicator}.tsx, services/{query.ts,queryStream.ts}, store/useChatStore.ts}
│   └── commits/{components/CommitsList.tsx, services/commits.ts, store/useCommitSummaryStore.ts}
├── services/base-service.ts    # BaseService — shared Axios wrapper every feature service extends
├── lib/{api-client.ts, utils.ts, runtime-safety.ts}
└── types/api.ts                 # TypeScript mirror of the backend's Pydantic schemas
```

This is a deliberate **feature-first** (not layer-first) organization: everything related to
"chat" lives under `features/chat/`, so a change to that feature rarely touches files outside
its folder. `lib/` and `services/base-service.ts` hold the small amount of genuinely
cross-feature infrastructure.

## Root layout and providers

`app/layout.tsx` wraps every page in:

```tsx
<Providers>          {/* TanStack Query's QueryClientProvider (installed, available for future use) */}
  <DashboardShell>{children}</DashboardShell>
</Providers>
```

`Providers` (`app/providers.tsx`) creates one `QueryClient` per mount (`useState(() => new QueryClient(...))`,
avoiding recreating it on every render) with `staleTime: 60_000` and `refetchOnWindowFocus: false`.

`DashboardShell` (`components/DashboardShell.tsx`) is the single biggest structural component:

- On mount, always calls `useRepoStore().fetchContext()` — this bootstraps "is there an active
  repository?" state regardless of which route the user lands on first (so deep-linking
  directly to `/chat` still works).
- **Conditionally renders two entirely different shells**: if no repository is active, it shows
  a minimal landing header/footer around `{children}` (the marketing/ingest page); if a
  repository *is* active, it renders the full app shell — a collapsible sidebar
  (`framer-motion`-animated width) with nav links (`Overview /`, `Chat /chat`, `Commits
  /commits`; `Pull Requests`/`Issues`/`File Explorer` are present as UI placeholders with no
  route wired up yet), a top bar showing the active repo name, and a scrollable content area.

## API client (`lib/api-client.ts`)

```ts
function resolveApiBaseUrl(): string {
  if (process.env.NEXT_PUBLIC_API_URL) return process.env.NEXT_PUBLIC_API_URL;
  if (typeof window !== 'undefined') return `http://${window.location.hostname}:8000/api/v1`;
  return `http://localhost:8000/api/v1`;
}
export const apiClient = axios.create({ baseURL: API_BASE_URL, timeout: 600000 });
export const API_WS_BASE_URL = API_BASE_URL.replace(/^http/, 'ws');
```

Key points:

- **No Next.js rewrite proxy.** The browser calls the FastAPI backend directly. This is
  explained in code comments: `next dev`'s built-in rewrite proxy has a hardcoded ~20s timeout
  independent of anything configured here, and a real multi-minute repository ingest routinely
  exceeds it — tearing down that proxied connection previously crashed the whole dev server.
- **Host resolution follows the page, not a hardcoded `localhost`.** If `NEXT_PUBLIC_API_URL`
  isn't set, the base URL is derived from `window.location.hostname` at request time — so
  opening the frontend from another device on the LAN (e.g. `http://192.168.1.7:3000`) still
  correctly targets `http://192.168.1.7:8000/api/v1` instead of trying to reach `localhost` on
  that device.
- **10-minute timeout** — a real repository ingest (clone + chunk + rate-limited Gemini
  embedding batches) can legitimately take minutes.
- **A response interceptor** unwraps Axios/FastAPI error shapes into a plain `Error` whose
  `.message` is `error.response.data.detail` (FastAPI's standard error body) when present,
  falling back to `error.message`, so every calling `try/catch` can just read `err.message`.
- `API_WS_BASE_URL` is the same resolved host with `http`→`ws`, used by the chat feature's
  streaming client.

## Service layer (`services/base-service.ts` + per-feature `*.ts`)

```ts
export abstract class BaseService {
  protected client: AxiosInstance = apiClient;
  protected async get<T>(url: string, config = {}): Promise<T> { ... }
  protected async post<T>(url: string, data = {}, config = {}): Promise<T> { ... }
  protected async delete<T>(url: string, config = {}): Promise<T> { ... }
}
```

Every feature has exactly one service class extending `BaseService`, implemented as a private
constructor + static `getInstance()` singleton, e.g.:

```ts
export class RepositoryService extends BaseService {
  private static instance: RepositoryService;
  private constructor() { super(); }
  public static getInstance(): RepositoryService { ... }
  public async getRepositoryContext(): Promise<RepositoryContextResponse> { return this.get('/repository'); }
  ...
}
export const repositoryService = RepositoryService.getInstance();
```

Services: `repositoryService` (`/repository`, `/repositories`, `/repositories/{name}/select`,
`DELETE /repositories/{name}`), `ingestionService` (`POST /ingest`), `queryService`
(`POST /query`), `commitsService` (`POST /commits/{hash}/summary`). Each method is typed
against the shared `types/api.ts` interfaces and calls exactly one backend endpoint — no
business logic lives here, only the HTTP call and its types.

## State management (Zustand)

Each feature owns one `create<...>((set, get) => ({...}))` store. No providers, no context —
components call the hook directly and select only the slices they need
(`useRepoStore((state) => state.repository)`), which keeps re-renders scoped.

| Store | File | State | Key actions |
|---|---|---|---|
| `useRepoStore` | `features/repo-metadata/store/useRepoStore.ts` | `repository, repoUrl, metadata, files, commits, pullRequests, isLoading, error, availableRepositories, isLoadingAvailable, availableError, isSelecting` | `fetchContext()`, `fetchAvailableRepositories()`, `selectRepository(name)`, `deleteRepository(name)`, `reset()` |
| `useIngestStore` | `features/ingestion/store/useIngestStore.ts` | `isIngesting, error, success, repository, filesProcessed, chunksCreated, repoUrl` | `ingestRepo(url)`, `reset()` |
| `useChatStore` | `features/chat/store/useChatStore.ts` | `messages: ChatMessage[], isLoading` | `sendMessage(question)`, `retryMessage(id)`, `clearChat()` |
| `useCommitSummaryStore` | `features/commits/store/useCommitSummaryStore.ts` | `summaries: Record<hash, {status, summary?, error?}>` | `summarizeCommit(hash)` |

All async actions follow the same shape: set a loading flag → call the service → on success
`set()` the new data and clear the flag → on failure, catch and `set()` an error message via
`getErrorMessage(err, fallback)`. Several actions (`selectRepository`, `ingestRepo`) also
**re-throw** after setting store-level error state, so a calling component can show inline
per-row errors (see `RepositoryManager` in
[06-frontend-features.md](06-frontend-features.md)) in addition to the store's own error field.

## `lib/runtime-safety.ts` — defensive response normalization

Backend responses are trusted for *shape* (both sides are hand-kept in sync) but not
necessarily for *content quality* — the AI-generated fields in particular (`summary`,
`technologies`, `suggested_questions`) can be `null`/missing if generation failed server-side.
This module centralizes coercion so every store doesn't repeat the same defensive checks:

- `asString`/`asStringArray` — type-guard + trim-check primitives.
- `normalizeRepositoryContext(value)` — coerces `metadata.technologies`,
  `detected_technologies`, and `suggested_questions` to `string[]` (never `undefined`), and
  `files`/`commits`/`pull_requests` to arrays.
- `normalizeIngestResponse(value)` — throws `'The server returned an invalid ingestion
  response.'` if `repository` is missing (this is the one field the rest of the app cannot
  proceed without), otherwise coerces numeric fields to finite numbers (defaulting to `0`).
- `normalizeRepositorySummaries(value)` — filters the `/repositories` list down to well-formed
  entries only, dropping anything without a `repository` name.
- `normalizeQueryResponse(value)` — defaults `answer` to a placeholder string and
  `retrieved_chunks` to `0` if the backend response is malformed.
- `appendLogLines(current, ...lines)` — used only by the ingestion progress-log simulation UI,
  filters out anything that isn't a non-empty string.
- `getErrorMessage(error, fallback)` — the one function nearly every store's `catch` block
  calls: unwraps an `Error`'s `.message`, a raw string, or falls back to a provided default.

## `types/api.ts` — the TypeScript/Pydantic contract

Hand-written interfaces mirroring every Pydantic model in `backend/src/api/schemas.py`, plus a
few backend-shaped-but-not-formally-schema'd types (`CommitMetadata`, `PullRequestMetadata`,
`RepositoryMetadata`) that describe the dict shapes returned inside
`RepositoryContextResponse.metadata` / `.commits` / `.pull_requests`. These are **not**
generated from the backend — they're maintained by hand, so **whenever a Pydantic schema
changes, `types/api.ts` must be updated to match** (there is no codegen step in this project).

Notice `RepositoryMetadata` carries *both* `summary`/`ai_summary`/`repository_summary` and
`technologies`/`detected_technologies` as alternate optional keys — `RepositoryDashboard`
reads whichever is populated (see [06-frontend-features.md](06-frontend-features.md)),
tolerating minor backend field-naming drift without a hard break.

## Styling and UI kit

- **Tailwind CSS v4** (`@tailwindcss/postcss`), configured via `components.json`
  (`"style": "base-nova"`, `"baseColor": "neutral"`, CSS variables enabled, no prefix).
- **shadcn** generates local component source (not an npm UI package) into `components/ui/` —
  currently just `button.tsx`, built on `@base-ui/react`'s headless `Button` primitive plus
  `class-variance-authority` (`cva`) for variant/size class composition (`variant`: default,
  outline, secondary, ghost, destructive, link; `size`: default, xs, sm, lg, icon, icon-xs,
  icon-sm, icon-lg).
- `lib/utils.ts` exports `cn(...)` = `twMerge(clsx(inputs))`, the standard shadcn class-merging
  helper used everywhere className logic is conditional.
- `lucide-react` for icons, `framer-motion` for the sidebar/panel/list transition animations
  throughout `DashboardShell`, `IngestPanel`, and `RepositoryPicker`.
- The whole UI is a fixed **dark theme** (`bg-zinc-950`/`text-zinc-100` base, indigo accent) —
  there is no light-mode toggle.
