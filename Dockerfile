# PDFNova — one image with every optional engine (LibreOffice, Tesseract, Chromium).
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 DATA_DIR=/data
RUN apt-get update && apt-get install -y --no-install-recommends \
        libreoffice-writer-nogui \
        tesseract-ocr tesseract-ocr-eng tesseract-ocr-hin tesseract-ocr-spa tesseract-ocr-fra tesseract-ocr-deu \
        fonts-dejavu fonts-noto-core fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt playwright \
    && playwright install --with-deps chromium

COPY app ./app
RUN useradd --create-home pdfnova && mkdir -p /data && chown pdfnova /data
USER pdfnova
VOLUME ["/data"]
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/tools')"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
