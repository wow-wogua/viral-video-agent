FROM python:3.12-slim

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# pip 使用清华镜像
RUN pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple

# HuggingFace 使用镜像
ENV HF_ENDPOINT=https://hf-mirror.com

COPY pyproject.toml .
RUN python -c "import tomllib; print('\\n'.join(tomllib.load(open('pyproject.toml', 'rb'))['project']['dependencies']))" > /tmp/requirements.txt \
    && pip install --no-cache-dir -r /tmp/requirements.txt

COPY . .
RUN pip install --no-cache-dir --no-deps .

EXPOSE 8000

CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
