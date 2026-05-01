# Multi-stage Dockerfile for the Lysos workspace HF Space.
#
# Stage 1: Build the Vite/React frontend
# Stage 2: Run the FastAPI backend with the built frontend served as static
#
# HF Space SDK: docker
# Build: docker build -t lysos-workspace .
# Run:   docker run -p 7860:7860 -e HF_TOKEN=$HF_TOKEN lysos-workspace
#
# For HF Space deployment, this exact Dockerfile is what gets pushed.

# -----------------------------------------------------------------------------
# Stage 1 — frontend build
# -----------------------------------------------------------------------------
FROM node:20-slim AS web-builder

WORKDIR /web
COPY web/package.json web/package-lock.json* ./
RUN npm ci || npm install

COPY web/ ./
RUN npm run build

# -----------------------------------------------------------------------------
# Stage 2 — Python backend with built frontend
# -----------------------------------------------------------------------------
# Use the AMD ROCm base for inference. For HF Spaces' default infra (CPU/Zero
# GPU), swap to python:3.11-slim and let HF Spaces handle GPU allocation.
FROM python:3.11-slim AS app

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV PIP_NO_CACHE_DIR=1
ENV HF_HUB_ENABLE_HF_TRANSFER=1
ENV HF_HOME=/data/.hf-cache

# OS deps
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        curl \
        ca-certificates \
        libxrender1 \
        libxext6 \
        libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Python deps — copy minimal Lysos package + install
COPY pyproject.toml ./
COPY src ./src

RUN pip install --upgrade pip && \
    pip install \
        "fastapi>=0.115.0" \
        "uvicorn[standard]>=0.32.0" \
        "sse-starlette>=2.1.3" \
        "httpx>=0.27.0" \
        "pydantic>=2.9.0" \
        "transformers>=4.45.0" \
        "accelerate>=1.0.0" \
        "peft>=0.13.0" \
        "huggingface-hub[hf_transfer]>=0.27.0" \
        "datasets>=3.0.0" \
        "rdkit>=2024.3.5" \
        "PyTDC>=1.1.0" \
        "numpy>=1.26.0" \
        "pandas>=2.2.0" \
        "scikit-learn>=1.5.0" \
        "torch>=2.5.0"

# Copy backend code
COPY workspace/api ./workspace/api

# Copy built frontend from Stage 1
COPY --from=web-builder /web/dist ./workspace/web/dist

# Make /data writable for HF cache
RUN mkdir -p /data && chmod 777 /data

EXPOSE 7860

# HF Spaces expects port 7860
CMD ["uvicorn", "workspace.api.server:app", "--host", "0.0.0.0", "--port", "7860"]
