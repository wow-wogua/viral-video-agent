import os
from dotenv import load_dotenv

load_dotenv()

ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")
ANTHROPIC_BASE_URL: str = os.getenv("ANTHROPIC_BASE_URL", "")
LLM_MODEL_ID: str = os.getenv("LLM_MODEL_ID", "mimo-v2.5-pro")

DEEPSEEK_API_KEY: str = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL: str = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
DEEPSEEK_MODEL_ID: str = os.getenv("DEEPSEEK_MODEL_ID", "deepseek-chat")

XFYUN_APPID: str = os.getenv("XFYUN_APPID", "")
XFYUN_SECRET_KEY: str = os.getenv("XFYUN_SECRET_KEY", "")
MIMO_API_KEY: str = os.getenv("MIMO_API_KEY", "") or ANTHROPIC_API_KEY
MIMO_ASR_BASE_URL: str = os.getenv("MIMO_ASR_BASE_URL", "https://api.xiaomimimo.com/v1")
MIMO_ASR_MODEL: str = os.getenv("MIMO_ASR_MODEL", "mimo-v2.5-asr")
MIMO_ASR_LANGUAGE: str = os.getenv("MIMO_ASR_LANGUAGE", "zh")
TRANSCRIPT_PROVIDER: str = os.getenv("TRANSCRIPT_PROVIDER", "mimo").lower()
ASR_MAX_BASE64_BYTES: int = int(os.getenv("ASR_MAX_BASE64_BYTES", str(10 * 1024 * 1024)))
ASR_MAX_VIDEO_SECONDS: int = int(os.getenv("ASR_MAX_VIDEO_SECONDS", "600"))

ANALYSIS_CONFIDENCE_THRESHOLD: float = float(os.getenv("ANALYSIS_CONFIDENCE_THRESHOLD", "0.8"))
ANALYST_MAX_ITERATIONS: int = int(os.getenv("ANALYST_MAX_ITERATIONS", "5"))
WRITER_MAX_REVISIONS: int = int(os.getenv("WRITER_MAX_REVISIONS", "3"))
GRAPH_VERSION: str = os.getenv("GRAPH_VERSION", "v2").lower()
V2_ANALYST_MAX_ITERATIONS: int = int(os.getenv("V2_ANALYST_MAX_ITERATIONS", "2"))
V2_WRITER_MAX_REVISIONS: int = int(os.getenv("V2_WRITER_MAX_REVISIONS", "1"))
V2_MIN_EVIDENCE_ITEMS: int = int(os.getenv("V2_MIN_EVIDENCE_ITEMS", "1"))

CHROMA_HOST: str = os.getenv("CHROMA_HOST", "127.0.0.1")
CHROMA_PORT: int = int(os.getenv("CHROMA_PORT", "8500"))
EMBEDDING_MODEL: str = os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")

REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
DATABASE_URL: str = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://viral_video:viral_video@localhost:5432/viral_video",
)
APP_ENV: str = os.getenv("APP_ENV", "development").lower()
JWT_SECRET: str = os.getenv("JWT_SECRET", "dev-only-change-me-at-least-32-bytes")
JWT_ALGORITHM: str = "HS256"
JWT_EXPIRE_MINUTES: int = int(os.getenv("JWT_EXPIRE_MINUTES", "10080"))
AUTH_COOKIE_NAME: str = os.getenv("AUTH_COOKIE_NAME", "viral_video_session")
COOKIE_SECURE: bool = APP_ENV == "production"
JOB_TIMEOUT_SECONDS: int = int(os.getenv("JOB_TIMEOUT_SECONDS", "600"))
JOB_MAX_RETRIES: int = int(os.getenv("JOB_MAX_RETRIES", "2"))
WORKER_MAX_JOBS: int = int(os.getenv("WORKER_MAX_JOBS", "2"))
USER_MONTHLY_JOB_LIMIT: int = int(os.getenv("USER_MONTHLY_JOB_LIMIT", "30"))
MCP_SERVER_URL: str = os.getenv("MCP_SERVER_URL", "http://127.0.0.1:8001/sse")
ENABLE_MOCK_TOOLS: bool = os.getenv("ENABLE_MOCK_TOOLS", "false").lower() == "true"

if APP_ENV == "production" and JWT_SECRET == "dev-only-change-me-at-least-32-bytes":
    raise RuntimeError("JWT_SECRET must be configured in production")
