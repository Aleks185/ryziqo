FROM python:3.12-slim

# Optional headless Chromium for JS-rendered pages (adds ~400 MB): --build-arg INSTALL_PLAYWRIGHT=true
ARG INSTALL_PLAYWRIGHT=false
# Local OCR fallback for screenshots without a vision model (~120 MB with OpenCV/ONNX Runtime)
ARG INSTALL_OCR=true

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

WORKDIR /app

# Copy dependency lists first for layer caching (runtime only — no test tooling in the image)
COPY backend/requirements.txt backend/requirements-playwright.txt backend/requirements-ocr.txt /app/
RUN pip install --upgrade pip && pip install -r /app/requirements.txt

RUN if [ "$INSTALL_OCR" = "true" ]; then \
        apt-get update \
        && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 \
        && rm -rf /var/lib/apt/lists/* \
        && pip install -r /app/requirements-ocr.txt; \
    fi

RUN if [ "$INSTALL_PLAYWRIGHT" = "true" ]; then \
        pip install -r /app/requirements-playwright.txt \
        && playwright install --with-deps chromium \
        && chmod -R a+rX /ms-playwright; \
    fi

# Copy backend source and static reference data
COPY backend/app /app/app
COPY data /app/data_seed

# Non-root user for container security
RUN useradd --create-home --shell /bin/bash appuser \
    && mkdir -p /data/object_store \
    && chown -R appuser:appuser /app /data

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health', timeout=3)" || exit 1

CMD ["uvicorn", "app.main:app", "--no-proxy-headers", "--host", "0.0.0.0", "--port", "8000"]
