# 06 — Frontend: Features

## Ingestion feature (`features/ingestion/`)

### `IngestPanel.tsx`

Rendered on the landing page (`app/page.tsx`) when no repository is active. Responsibilities:

1. **Client-side URL validation** (`validateUrl`) before ever calling the backend: must parse
   as a URL, hostname must be exactly `github.com`, and the path must have at least two
   segments (`owner/repo`).
2. **Fires the real ingestion call**: `useIngestStore().ingestRepo(cleanUrl)` → `POST /ingest`.
3. **A cosmetic progress simulation** runs concurrently with the real network call — a
   `setInterval`-driven fake progress bar (`SIM_STEPS`, six labeled stages from "Connecting to
   GitHub..." to "Indexing complete!") and a scrolling fake terminal log
   (`appendLogLines`-guarded so malformed entries can't render). This is UI theater layered on
   top of the real request; it does **not** reflect actual backend progress (the backend has no
   ingestion-progress-streaming endpoint) — when the real `ingestRepo` promise resolves, the
   panel snaps the fake bar to 100%, shows a success log line, waits ~1s, then calls
   `useRepoStore().fetchContext()` to load the freshly-activated repository's dashboard.
4. On failure, shows the real error message from `getErrorMessage(err, ...)` and stops the
   simulation.
5. Offers three example repo URLs (FastAPI, ChromaDB, LangGraph) as one-click fill buttons.

If you're rebuilding this: the simulated progress bar is optional polish, not core
functionality — the essential piece is just `await ingestionService.ingestRepository(repoUrl)`
followed by refreshing repo state.

### `useIngestStore` / `ingestion.ts` service

Straightforward: `ingestRepo(url)` sets `isIngesting=true`, calls
`ingestionService.ingestRepository(url)` (→ `POST /ingest`), normalizes the response with
`normalizeIngestResponse`, stores `repository`/`filesProcessed`/`chunksCreated`/`repoUrl`, and
**re-throws** on failure (after recording the error) so `IngestPanel` can react locally too.

## Repository metadata feature (`features/repo-metadata/`)

Three components share `useRepoStore`:

### `RepositoryPicker.tsx`

Shown on the landing page above `IngestPanel`, *only* if `availableRepositories.length > 0`
(i.e. at least one repo is already indexed) — fetched on mount via
`fetchAvailableRepositories()` (`GET /repositories`). Renders each as a clickable card;
clicking calls `selectRepository(name)` (`POST /repositories/{name}/select`), which activates
it without re-ingesting.

### `RepositoryDashboard.tsx`

Rendered on `/` once `useRepoStore().repository` is set (replacing the landing page — see
`app/page.tsx`'s `if (repository) return <RepositoryDashboard />`). Reads `metadata` from the
store and displays, tolerating multiple possible backend field names per value (see
[05-frontend-architecture.md](05-frontend-architecture.md#typesapits--the-typescriptpydantic-contract)):

- Hero section: repo name (`name` → `full_name` → collection `repository` id, in that
  fallback order), owner, primary language, last-updated date, description.
- Metric tiles: stars, forks, default branch, primary language.
- **AI-generated summary** card (`ai_summary` → `repository_summary` → `summary`).
- **Detected technologies** as pill badges (`detected_technologies` → `technologies`).
- **Suggested questions** grid — these are exactly what populates the chat page's empty-state
  suggestion buttons (`app/chat/page.tsx` reads `metadata?.suggested_questions`).

All fields render `"Not available"` rather than blank/undefined when missing, via small
`asDisplayText`/`formatCount`/`formatDate` helpers local to this file.

### `RepositoryManager.tsx`

Rendered on `/settings`. Lists every indexed repository (same `availableRepositories` data as
the picker) with three per-row actions, each independently tracked with local
`busyRepo`/`busyAction` state so only the clicked row shows a spinner:

- **Activate** — `selectRepository(name)`, disabled if already active.
- **Re-ingest** — `useIngestStore().ingestRepo(item.repo_url)` (full re-clone + re-embed),
  disabled if the collection has no recorded `repo_url` (can't re-ingest without a source).
- **Delete** — a two-step confirm (`pendingDelete` state shows "Delete this repository? [Confirm] [Cancel]"
  inline before calling `deleteRepository(name)`).

Row-level errors are shown inline (`rowError` state) independent of the store's global `error`
field, since multiple rows could in principle be interacted with in sequence.

## Chat feature (`features/chat/`)

### Data flow: streaming-first with REST fallback

`useChatStore.sendMessage(question)`:

1. Builds a bounded history payload (`buildHistoryPayload` — last 20 **completed** messages
   only; pending/errored bubbles are excluded since their content isn't reliable/final).
2. Optimistically appends a `user` message and a `pending` `assistant` placeholder message to
   `messages`, sets `isLoading = true`.
3. Calls `runQuery`, which:
   - **First tries** `queryStreamClient.query(question, history, { onToken })` — the WebSocket
     path (see below). Tokens arrive via the `onToken` callback and are appended to the
     placeholder message's `content` live (`appendToken`), so the UI streams in real time.
   - **On any streaming failure** (connection error, timeout, server-side error event), falls
     back silently to `queryService.queryRepository(question, history)` (blocking `POST
     /query`) — the user experience degrades to "wait, then see the full answer" but still
     succeeds.
   - **On failure of both paths**, marks the message `status: 'error'` with the error text as
     content, and the UI shows a **Retry** button.
4. `finalizeMessage` sets `status: 'complete'`, `content` = final answer, plus `sourceFiles` and
   `retrievedChunks` for the citation footer.

`retryMessage(assistantMessageId)` re-runs `runQuery` for a previously-errored message, rebuilding
history from everything **before** the failed exchange (so the failed Q/A pair itself isn't
included).

### `queryStreamClient` (`services/queryStream.ts`)

A hand-rolled WebSocket client (`QueryStreamClient` class, one shared instance):

- `connect()` opens `${API_WS_BASE_URL}/ws/query`, resolving once `onopen` fires or rejecting
  after an 8-second connect timeout / on `onerror`. Reuses an already-open socket; concurrent
  callers share one in-flight connect promise.
- `query(question, history, handlers)` sends `{question, history}` as JSON, then listens for
  `message` events and dispatches on the event's `type` field: `retrieval` → optional
  `handlers.onRetrieval`, `token` → `handlers.onToken(text)`, `done` → resolves with
  `{answer, sourceFiles, retrievedChunks}`, `error` → rejects with the server's `detail`.
  A `close` event before `done`/`error` also rejects (`'Connection to the assistant was lost.'`).
- The socket is **kept open and reused** across questions — matching the backend's
  one-connection-many-questions loop. Callers are expected to serialize questions themselves;
  `useChatStore`'s `isLoading` gate on `ChatInput` already prevents overlapping sends.

### Chat UI components

- `ChatWindow` — composes `ChatHeader` + `MessageList` + `ChatInput`, entirely self-contained
  (only depends on `useChatStore`), so it can be dropped onto any page.
- `ChatHeader` — title + a "Clear" button (disabled when there are no messages).
- `MessageList` — empty state shows a prompt plus clickable `suggestedQuestions` (from the
  repository's AI overview); otherwise renders each `MessageBubble` and auto-scrolls to bottom
  on new messages.
- `MessageBubble` — user bubbles are plain text (right-aligned, indigo); assistant bubbles
  render through `MarkdownRenderer` (left-aligned), or `TypingIndicator` while pending with no
  content yet, or an error style with a **Retry** button when `status === 'error'`. Non-error,
  non-pending assistant bubbles show `SourceCitations` if `sourceFiles.length > 0`.
- `MarkdownRenderer` — `react-markdown` + `remark-gfm`, with a custom `code` renderer that uses
  `react-syntax-highlighter` (Prism, `oneDark` theme) for fenced code blocks and a simpler
  inline style for inline code; links open in a new tab (`target="_blank" rel="noopener
  noreferrer"`).
- `SourceCitations` — renders the answer's `source_files` as small file-icon chips, with an
  optional "N chunks retrieved" label.
- `TypingIndicator` — three bouncing dots, `role="status"` for accessibility.
- `ChatInput` — an auto-growing `<textarea>` (height recalculated on input, capped at 160px),
  `Enter` sends / `Shift+Enter` inserts a newline, disabled while `isLoading`.

## Commits feature (`features/commits/`)

- `CommitsList.tsx` reads `commits` straight from `useRepoStore` (populated at ingestion/select
  time — no separate fetch). Each `CommitCard` shows short hash, author, date, first line of
  the commit message, and +/-/files-changed counts.
- Each card has an on-demand **AI summarize** button wired to `useCommitSummaryStore`, keyed by
  commit hash so each commit's summary request/state is independent:
  `idle → loading → done (renders summary) | error (shows Retry, error as a tooltip)`.
  `summarizeCommit(hash)` calls `commitsService.summarizeCommit(hash)` →
  `POST /commits/{hash}/summary`, which (server-side) reuses the diff already captured at
  ingestion time rather than making a fresh GitHub call.

## App routes (`app/`)

| Route | Page | Guard |
|---|---|---|
| `/` | Landing (`IngestPanel` + `RepositoryPicker`) or `RepositoryDashboard` | Switches based on `useRepoStore().repository` |
| `/chat` | `ChatWindow` | If no active repository, shows "Go ingest a repository" link instead |
| `/commits` | `CommitsList` | Same guard as `/chat` |
| `/settings` | `RepositoryManager` | No guard — always shows the list (possibly empty) |

Each route with data dependencies has a matching `loading.tsx` (Next.js route-level Suspense
fallback) showing a spinner + short label. `error.tsx` is a client-side error boundary for the
whole app (logs to console, offers "Try again" / "Go home"); `not-found.tsx` is the 404 page.
Both use the shadcn `Button`'s `render={<Link href="/" />}` prop pattern (from `@base-ui/react`)
to make the button itself behave as a Next.js `<Link>`.
