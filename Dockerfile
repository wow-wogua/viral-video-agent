FROM python:3.12-slim

WORKDIR /app

# pip 使用清华镜像
RUN pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple

# HuggingFace 使用镜像
ENV HF_ENDPOINT=https://hf-mirror.com

# 先装依赖（利用 Docker 缓存，依赖不变时不会重新装）
COPY pyproject.toml .
RUN pip install --no-cache-dir langgraph langchain-core langchain-anthropic langchain-openai \
    fastapi uvicorn python-dotenv httpx aiosqlite chromadb tiktoken mcp "celery[redis]" redis pyyaml

COPY . .

EXPOSE 8000

CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
