FROM python:3.11-slim

WORKDIR /app

# 系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ \
    && rm -rf /var/lib/apt/lists/*

# 先装依赖（利用 Docker 层缓存）
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制应用代码和知识库
COPY app.py .
COPY data/ ./data/

# 环境变量默认值（实际通过 docker-compose 注入）
ENV PARENT_CHAT_HOST=0.0.0.0
ENV PARENT_CHAT_PORT=7860

EXPOSE 7860

CMD ["python", "app.py"]
