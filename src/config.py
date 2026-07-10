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

ANALYSIS_CONFIDENCE_THRESHOLD: float = float(os.getenv("ANALYSIS_CONFIDENCE_THRESHOLD", "0.8"))
ANALYST_MAX_ITERATIONS: int = int(os.getenv("ANALYST_MAX_ITERATIONS", "5"))
WRITER_MAX_REVISIONS: int = int(os.getenv("WRITER_MAX_REVISIONS", "3"))

CHROMA_HOST: str = os.getenv("CHROMA_HOST", "localhost")
CHROMA_PORT: int = int(os.getenv("CHROMA_PORT", "8500"))
EMBEDDING_MODEL: str = os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")

REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
MCP_SERVER_URL: str = os.getenv("MCP_SERVER_URL", "http://localhost:8001/sse")
