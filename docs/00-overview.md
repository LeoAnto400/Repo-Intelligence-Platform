# 00 — Project Overview

## What this project is

A **Multi-Agent GitHub Repository Intelligence Assistant**: a web app that lets a user
paste a GitHub repository URL, indexes the entire codebase into a vector database, and
then answers natural-language questions about that codebase ("How does authentication
work?", "Where is the retry logic for the Gemini API?") with answers grounded in the
actual source code — not general LLM knowledge.

It is a full-stack project:

- **Backend**: Python, FastAPI, LangGraph, ChromaDB, Google Gemini
- **Frontend**: Next.js (App Router), React 19, TypeScript, Zustand, Tailwind CSS v4

## Core use cases

1. **Explain repository architecture** — "What does this project do end to end?"
2. **Explain specific code functionality** — "How does the retry logic in GeminiService work?"
3. **Locate implementations** — "Where is rate limiting enforced?"
4. **Trace dependencies** — "What calls `VectorStoreManager.add_documents`?"
5. **Generate documentation** — summarize commits, summarize the repo itself

## The user journey

```
User pastes a GitHub URL
        │
        ▼
Backend clones the repo, chunks every source file, embeds each chunk with
Gemini, and stores the vectors in a ChromaDB collection named after the repo
        │
        ▼
Backend also fetches repo metadata (stars, commits, PRs) from the GitHub API
and asks Gemini to write a short AI summary + detected tech stack + suggested
questions from a sample of the ingested chunks
        │
        ▼
Frontend shows a dashboard: AI summary, tech stack, commit history, and a
chat window
        │
        ▼
User asks a question in the chat → Orchestrator runs Retrieval → Rerank →
Analysis → grounded answer streamed back token-by-token over a WebSocket
```

## Tech stack at a glance

| Layer | Technology | Why |
|---|---|---|
| Backend web framework | **FastAPI** (+ Uvicorn) | async-first, automatic OpenAPI docs, dependency injection |
| Agent orchestration | **LangGraph** | explicit state-machine graph for the retrieve → analyze pipeline |
| Vector database | **ChromaDB** (local, persistent) | zero-ops embedded vector store, cosine similarity search |
| Embeddings | **Gemini `gemini-embedding-001`** | `retrieval_document` vs `retrieval_query` task types tuned for RAG |
| LLM (answers, reranking, summaries) | **Gemini 2.5 Flash** | fast, cheap, good enough for RAG-grounded answers |
| GitHub access | **PyGithub** + `git clone --depth 1` (subprocess) | metadata via REST API, source via a shallow clone |
| Config | **pydantic-settings** | typed settings loaded from `.env` |
| Frontend framework | **Next.js 15 (App Router)** + **React 19** | file-based routing, client components, streaming-friendly |
| Frontend state | **Zustand** | tiny, hook-based, no boilerplate providers |
| Frontend data fetching | **Axios** + a hand-rolled `BaseService`/`*Service` singleton pattern; **TanStack Query** is installed and provided but not yet used for the core flows |
| Styling / UI kit | **Tailwind CSS v4** + **shadcn** (`base-nova` style) + **@base-ui/react** primitives + `lucide-react` icons | dark, dashboard-style UI |
| Markdown / code rendering | `react-markdown` + `remark-gfm` + `react-syntax-highlighter` | renders LLM answers with fenced code blocks |
| Motion | `framer-motion` | sidebar/panel transitions |
| Testing | **pytest** (backend), **Vitest** + **Testing Library** (frontend) | |
| CI | **GitHub Actions** (`.github/workflows/ci.yml`) | lint, type-check, test, build on every push/PR |

## Repository layout

```
repo-intelligence-Platform/
├── main.py                      # dev entrypoint: `python main.py` runs uvicorn
├── requirements.txt              # backend Python dependencies
├── backend/
│   ├── .env.example               # backend environment variable template
│   ├── src/
│   │   ├── api/
│   │   │   ├── main.py            # FastAPI app: CORS, lifespan, /health, exception handler
│   │   │   ├── routes.py          # all REST + WebSocket endpoints
│   │   │   └── schemas.py         # Pydantic request/response models
│   │   ├── agents/
│   │   │   ├── base.py            # BaseAgent abstract interface
│   │   │   ├── retrieval.py       # RetrievalAgent (ANN search + Gemini rerank)
│   │   │   ├── analysis.py        # AnalysisAgent (prompt building, answer generation)
│   │   │   └── orchestrator.py    # Orchestrator (LangGraph StateGraph)
│   │   ├── services/
│   │   │   ├── github.py          # clone + scan a repo, fetch metadata/commits/PRs
│   │   │   ├── chunker.py         # CodeChunker: AST-based + sliding-window chunking
│   │   │   ├── gemini.py          # GeminiService: embeddings + generation + rate limiting
│   │   │   └── ingestion.py       # filter_chunks_for_embedding helper
│   │   ├── db/
│   │   │   └── chroma.py          # VectorStoreManager: ChromaDB wrapper
│   │   └── core/
│   │       ├── config.py          # Settings (pydantic-settings)
│   │       ├── logging.py         # root logger configuration
│   │       └── rate_limit.py      # InMemoryRateLimiter (sliding window)
│   ├── tests/                     # pytest suite, one file per module/behavior
│   └── scripts/                   # manual pipeline test scripts (not part of CI)
├── frontend/
│   ├── next.config.ts
│   ├── components.json            # shadcn config
│   ├── vitest.config.ts
│   └── src/
│       ├── app/                   # Next.js App Router pages (/, /chat, /commits, /settings)
│       ├── components/            # DashboardShell (sidebar/nav) + shared ui/ (shadcn Button)
│       ├── features/
│       │   ├── ingestion/         # IngestPanel + useIngestStore + ingestion service
│       │   ├── repo-metadata/     # RepositoryDashboard/Picker/Manager + useRepoStore
│       │   ├── chat/              # ChatWindow + useChatStore + REST/WebSocket query clients
│       │   └── commits/           # CommitsList + useCommitSummaryStore
│       ├── services/base-service.ts  # shared Axios wrapper all feature services extend
│       ├── lib/                   # api-client.ts, utils.ts, runtime-safety.ts
│       └── types/api.ts           # TypeScript types mirroring backend Pydantic schemas
└── .github/workflows/ci.yml
```

## How to read the rest of these docs

| File | Covers |
|---|---|
| [01-architecture.md](01-architecture.md) | System diagram, ingestion pipeline, query pipeline, design decisions |
| [02-backend-ingestion-pipeline.md](02-backend-ingestion-pipeline.md) | `GitHubService`, `CodeChunker`, `GeminiService`, `VectorStoreManager` |
| [03-backend-agents-orchestration.md](03-backend-agents-orchestration.md) | `RetrievalAgent`, `AnalysisAgent`, `Orchestrator` (LangGraph) |
| [04-backend-api-layer.md](04-backend-api-layer.md) | FastAPI app, config, rate limiting, every route, request/response shapes |
| [05-frontend-architecture.md](05-frontend-architecture.md) | Next.js structure, API client, service layer, Zustand stores, types |
| [06-frontend-features.md](06-frontend-features.md) | Ingestion UI, repository dashboard, chat UI (incl. streaming), commits UI |
| [07-testing-and-ci.md](07-testing-and-ci.md) | Test suites, what each test file verifies, the CI workflow |
| [08-environment-and-running-locally.md](08-environment-and-running-locally.md) | Environment variables, how to run both apps locally |
| [09-build-from-scratch-tutorial.md](09-build-from-scratch-tutorial.md) | A step-by-step build order to reproduce this whole project yourself |

The original one-page design sketch that kicked off this project is preserved at
[architecture.md](architecture.md) for historical context; the numbered docs above
are the authoritative, detailed reference.
