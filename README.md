# GitHub Repository Intelligence Assistant

A multi-agent codebase intelligence assistant built with FastAPI, ChromaDB, Gemini, and LangGraph.

## Architecture

The project consists of three specialized agents that coordinate to answer user questions about codebases:

1. **RetrievalAgent**: Queries the local Chroma vector database to extract the most relevant code chunks for a given question.
2. **AnalysisAgent**: Utilizes Gemini LLM to analyze the retrieved code snippets and synthesize detailed explanations.
3. **Orchestrator**: Routes user queries, coordinates state, and executes flow transitions between the agents.

## Project Structure

`	ext
backend/
+-- src/agents/       # Multi-agent implementations
+-- src/api/          # FastAPI application and routes
+-- src/core/         # Configuration management
+-- src/db/           # ChromaDB wrapper
+-- src/services/     # Gemini and GitHub integrations
frontend/            # Next.js user interface
` 

## Setup and running

1. Create "backend/.env" and set the required Gemini and GitHub credentials.
2. Install backend dependencies:

`powershell
pip install -r requirements.txt
` 

3. In one terminal, start the backend from its directory:

`powershell
cd backend
python -m uvicorn src.api.main:app --reload --reload-dir src --host 0.0.0.0 --port 8000
` 

4. In a second terminal, start the frontend:

`powershell
cd frontend
npm install
npm run dev
` 

Open the frontend at "http://localhost:3000". The frontend calls the FastAPI backend directly (not through a Next.js rewrite - `next dev`'s rewrite proxy has a hardcoded ~20s timeout that would kill any real repository ingestion), resolving the backend host from whichever host the page was loaded from, so this also works when opened via the configured LAN address.
