FROM python:3.9

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

# Add these lines to fix permissions
RUN chmod -R 755 /app
USER root

# Expose the port
EXPOSE 10000

# Update the CMD to specify host and port
CMD ["gunicorn", "main:app", "--workers", "4", "--worker-class", "uvicorn.workers.UvicornWorker", "--bind", "0.0.0.0:10000"] 