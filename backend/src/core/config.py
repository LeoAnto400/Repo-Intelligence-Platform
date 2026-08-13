from pydantic_settings import BaseSettings
from pydantic import Field

class Settings(BaseSettings):
    """
    Application settings loaded from environment variables and/or a .env file.
    """
    PROJECT_NAME: str = "GitHub Repository Intelligence Assistant"
    API_V1_STR: str = "/api/v1"
    LOG_LEVEL: str = Field("INFO", description="Root logger level (DEBUG, INFO, WARNING, ERROR)")

    # API Keys & Credentials
    GEMINI_API_KEY: str = Field("", description="Google Gemini API Key for LLM and embeddings generation")
    GITHUB_TOKEN: str | None = Field(None, description="GitHub personal access token (optional, for higher rate limits)")
    GEMINI_EMBEDDING_BATCH_SIZE: int = Field(8, description="Maximum number of chunks to send per Gemini embedding request")
    GEMINI_EMBEDDING_MAX_BATCH_CHARS: int = Field(12000, description="Maximum total characters to send per Gemini embedding request")
    GEMINI_EMBEDDING_BATCH_DELAY_SECONDS: float = Field(0.5, description="Delay between Gemini embedding sub-batches")
    
    # Ingestion Pipeline Resilience Settings
    EMBED_BATCH_SIZE: int = Field(5, description="Maximum number of chunks to send per Gemini embedding request")
    EMBED_BATCH_DELAY: float = Field(0.5, description="Delay between Gemini embedding batches in seconds")
    MAX_RETRIES: int = Field(5, description="Maximum retries for rate-limited calls")
    MAX_TOKENS_PER_BATCH: int = Field(10000, description="Maximum estimated input tokens per single embedding request")
    MAX_REQUESTS_PER_MINUTE: int = Field(100, description="Maximum API requests per minute to stay below limit")
    MAX_TOKENS_PER_MINUTE: int = Field(
        1_000_000,
        description=(
            "Maximum estimated tokens sent to the Gemini API per rolling 60-second "
            "window. Must stay well above MAX_TOKENS_PER_BATCH - it bounds total "
            "throughput, not a single request, and reusing the per-batch cap here "
            "throttles ingestion to ~1 batch/minute regardless of repo size."
        ),
    )
    
    # Vector Database
    CHROMA_DB_DIR: str = Field("./chroma_db", description="Local directory path where ChromaDB collections are stored")

    # Retrieval & Reranking
    RETRIEVAL_TOP_K: int = Field(20, description="Number of ANN candidates fetched from ChromaDB before reranking")
    RETRIEVAL_FINAL_K: int = Field(5, description="Number of reranked chunks passed to the LLM for answer generation")

    # Request-level rate limiting (per client IP). Separate from the Gemini
    # API rate limiter above, which throttles outbound calls to Google.
    INGEST_RATE_LIMIT_PER_MINUTE: int = Field(5, description="Maximum /ingest requests allowed per client IP per minute")
    QUERY_RATE_LIMIT_PER_MINUTE: int = Field(20, description="Maximum /query requests (REST or websocket) allowed per client IP per minute")

    class Config:
        env_file = ".env"
        case_sensitive = True

settings = Settings()
