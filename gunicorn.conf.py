# Gunicorn configuration
workers = 4
worker_class = "uvicorn.workers.UvicornWorker"
bind = "0.0.0.0:10000"
keepalive = 120
timeout = 120
graceful_timeout = 60
worker_connections = 1000 