# Documentation

Detailed, from-scratch documentation for the **GitHub Repository Intelligence Assistant** — a
multi-agent app that ingests a GitHub repository into a vector database and answers questions
about it with a FastAPI + LangGraph + ChromaDB + Gemini backend and a Next.js + Zustand frontend.

Read in order for a full understanding, or jump directly to what you need:

1. **[00-overview.md](00-overview.md)** — What this is, the user journey, tech stack, repo layout
2. **[01-architecture.md](01-architecture.md)** — System diagram, the two pipelines (ingestion, query), key design decisions
3. **[02-backend-ingestion-pipeline.md](02-backend-ingestion-pipeline.md)** — `GitHubService`, `CodeChunker`, `GeminiService`, `VectorStoreManager`
4. **[03-backend-agents-orchestration.md](03-backend-agents-orchestration.md)** — `RetrievalAgent`, `AnalysisAgent`, the LangGraph `Orchestrator`
5. **[04-backend-api-layer.md](04-backend-api-layer.md)** — FastAPI app, config, rate limiting, every endpoint
6. **[05-frontend-architecture.md](05-frontend-architecture.md)** — Next.js structure, API client, service layer, Zustand stores, types
7. **[06-frontend-features.md](06-frontend-features.md)** — Ingestion UI, repository dashboard, streaming chat UI, commits UI
8. **[07-testing-and-ci.md](07-testing-and-ci.md)** — What each test file verifies, the GitHub Actions CI workflow
9. **[08-environment-and-running-locally.md](08-environment-and-running-locally.md)** — Environment variables, running both apps locally
10. **[09-build-from-scratch-tutorial.md](09-build-from-scratch-tutorial.md)** — A staged build order to reproduce this entire project yourself, with checkpoints at each stage

[architecture.md](architecture.md) is the original one-paragraph design sketch that started
this project — kept for historical context; everything above supersedes it with the actual
as-built system.
