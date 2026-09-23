FROM pytorch/pytorch:2.7.1-cuda12.8-cudnn9-runtime
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
COPY requirements.in ./
RUN pip install --no-cache-dir -r requirements.in
COPY backend ./backend
COPY index.html app.js api-client.js matcher-core.js styles.css ./
EXPOSE 8000
CMD ["python", "-m", "backend.cli", "serve"]
