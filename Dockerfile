# PDFNova — one image with every optional engine (LibreOffice, Tesseract, Chromium).
FROM python:3.12-slim
ARG DEBIAN_MIRROR=deb.debian.org

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 DATA_DIR=/data PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
RUN printf 'Acquire::http::Timeout "20";\nAcquire::https::Timeout "20";\nAcquire::Retries "5";\n' > /etc/apt/apt.conf.d/80-download-retries \
    && sed -i "s|http://deb.debian.org|https://${DEBIAN_MIRROR}|g" /etc/apt/sources.list.d/debian.sources \
    && apt-get update && apt-get install -y --no-install-recommends \
        libreoffice-writer-nogui \
        tesseract-ocr tesseract-ocr-eng tesseract-ocr-hin tesseract-ocr-spa tesseract-ocr-fra tesseract-ocr-deu \
        fonts-dejavu fonts-noto-core fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt requirements-lock.txt ./
RUN pip install --no-cache-dir -r requirements-lock.txt \
    && playwright install --with-deps chromium \
    && chmod -R a+rX /ms-playwright

COPY app ./app
RUN useradd --create-home pdfnova && mkdir -p /data && chown pdfnova /data
USER pdfnova
VOLUME ["/data"]
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/tools')"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
