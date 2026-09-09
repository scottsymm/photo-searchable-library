FROM python:3.12-slim

WORKDIR /app
COPY packages/core /app/packages/core
COPY apps/api /app/apps/api

RUN pip install --no-cache-dir -e /app/packages/core \
    && pip install --no-cache-dir -e /app/apps/api

ENV PICS_DB=/data/catalog.db
ENV PICS_LIBRARY=/library
EXPOSE 8000
CMD ["uvicorn", "api.main:app", "--app-dir", "/app/apps/api", "--host", "0.0.0.0", "--port", "8000"]
