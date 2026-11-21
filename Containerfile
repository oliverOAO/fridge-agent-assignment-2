FROM docker.io/library/python:3.11-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 FRIDGE_DB=/app/data/fridge.sqlite3
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && mkdir -p /app/data
COPY fridge fridge
COPY data data
COPY tests tests
COPY app.py .
EXPOSE 8501
CMD ["streamlit", "run", "app.py", "--server.address=0.0.0.0", "--server.port=8501", "--server.headless=true", "--browser.gatherUsageStats=false"]
