FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    exiftool ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY LICENSE /LICENSE
COPY packages/core /app/packages/core
COPY services/worker /app/services/worker

RUN pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu torch \
    && pip install --no-cache-dir -e /app/packages/core \
    && pip install --no-cache-dir -e /app/services/worker

ENV PICS_DB=/data/catalog.db
ENV PICS_LIBRARY=/library
ENV HF_HOME=/models/huggingface
ENV INSIGHTFACE_ROOT=/models/insightface
ENV PYTHONPATH=/app/services/worker
EXPOSE 9090
CMD ["python", "-m", "worker.service"]
