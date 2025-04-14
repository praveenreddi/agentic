# agentic_inventory.conf.py for production/container deploy

workers = 4
worker_class = "uvicorn.workers.UvicornWorker"
bind = "0.0.0.0:8080"
preload_app = True
accesslog = "-"
errorlog = "-"
timeout = 60
