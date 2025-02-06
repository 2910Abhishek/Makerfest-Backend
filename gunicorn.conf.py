# Gunicorn configuration
workers = 2
worker_class = "uvicorn.workers.UvicornWorker"
bind = "0.0.0.0:10000"
timeout = 120 