FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=8104 ATLAS_DB_PATH=/tmp/atlas.db
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && useradd --create-home atlas
COPY atlas ./atlas
COPY static ./static
USER atlas
EXPOSE 8104
CMD ["sh", "-c", "uvicorn atlas.app:app --host 0.0.0.0 --port ${PORT:-8104} --workers 1"]
