# KidoAI 知识图谱模块 Dockerfile
# 基于 Python 3.12-slim 构建
FROM python:3.12-slim

WORKDIR /app

# 国内 pip 镜像加速
RUN pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple \
    && pip config set global.trusted-host pypi.tuna.tsinghua.edu.cn

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 7861

# 默认监听 7861 端口
ENV NEO4J_GRADIO_HOST=0.0.0.0
ENV NEO4J_GRADIO_PORT=7861

CMD ["python", "gradio_app.py"]
