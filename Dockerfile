FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /srv
COPY requirements.txt requirements-ai.txt ./
RUN pip install --no-cache-dir -r requirements-ai.txt
COPY main.py .
COPY jobengine ./jobengine
RUN useradd --create-home appuser && mkdir /data && chown appuser /data
USER appuser
ENV DB_PATH=/data/job_engine.db PREFILL_ENABLED=0
EXPOSE 8000
# Always set APP_PASSWORD when running this container anywhere but your own machine.
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
