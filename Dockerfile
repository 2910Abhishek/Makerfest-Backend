FROM python:3.9-slim

# Set working directory and environment variables
WORKDIR /app
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first to leverage Docker cache
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create a non-root user and switch to it
RUN useradd -m -r appuser && \
    chown -R appuser:appuser /app
USER appuser

# Expose the port
EXPOSE 10000

# Start the application
CMD ["gunicorn", "--config", "gunicorn.conf.py", "main:app"] 