"""
Main application module for the Agentic Inventory Service.

This module initializes the FastAPI application with all routes.
"""

import os
import uvicorn
from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from agentic_inventory.backend.api.chats import router as chat_router
from agentic_inventory.backend.api.jobs import router as job_router
from agentic_inventory.backend.jobs.scheduler import scheduler
from agentic_inventory.backend.storage.storage_sessions import StorageSessionsClient
from agentic_inventory.utils import config
from agentic_inventory.utils.extensions import logger


# Get Cosmos DB client
def get_storage():
    return StorageSessionsClient()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan event handler for FastAPI application."""
    # Startup
    logger.info("Starting up application...")
    try:
        await scheduler.start()
        logger.info("Job scheduler started")
    except Exception as e:
        logger.error(f"Error starting scheduler: {str(e)}")

    yield

    # Shutdown
    logger.info("Shutting down application...")
    try:
        scheduler.shutdown()
        logger.info("Job scheduler stopped")
    except Exception as e:
        logger.error(f"Error stopping scheduler: {str(e)}")


# Create FastAPI app
app = FastAPI(
    title="HGV Agentic Inventory Service",
    description="API for the HGV Agentic Inventory Service",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API routers - Only include chat and job routers
app.include_router(chat_router, prefix="/api")
app.include_router(job_router, prefix="/api")


# Health check endpoint
@app.get("/api/health")
async def health_check():
    """Health check endpoint."""
    logger.debug("Health check requested")
    return {"status": "healthy", "version": config.API_VERSION}


# Available tools endpoint
@app.get("/api/tools")
async def get_tools():
    """Get all available tools in the framework."""
    from agentic_inventory.backend.tools.tools import function_composer

    logger.info("Retrieving available tools")
    tools = list(function_composer.get_registered_functions())
    logger.debug(f"Found {len(tools)} tools")
    return {
        "tools": tools,
        "count": len(tools),
    }


# Cosmos DB containers info endpoint (for debugging)
@app.get("/api/storage/info")
async def get_storage_info(storage=Depends(get_storage)):
    """Get information about the Cosmos DB containers."""
    try:
        # Get available containers
        containers = []
        for container_name in ["UserSessions", "SessionMessages"]:
            try:
                container_info = {"name": container_name, "status": "available"}
                containers.append(container_info)
            except Exception:
                containers.append({"name": container_name, "status": "unavailable"})

        return {"database": storage.database.id, "containers": containers, "status": "connected"}
    except Exception as e:
        logger.error(f"Error accessing storage: {str(e)}")
        return {"status": "error", "error": str(e)}


# Custom StaticFiles class to serve SPA
class SPAStaticFiles(StaticFiles):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.html = kwargs.get("html", False)


# Check if the frontend dist folder exists
frontend_dist_path = "agentic_inventory/frontend/dist/hilton-chat-angular/browser"
if os.path.exists(frontend_dist_path):
    app.mount(
        "/",
        SPAStaticFiles(directory=frontend_dist_path, html=True),
        name="frontend",
    )
    logger.info(f"Frontend static files mounted from {frontend_dist_path}")
else:
    logger.warning(f"Frontend dist folder not found at {frontend_dist_path}. Skipping static file mounting.")

if __name__ == "__main__":
    uvicorn.run("agentic_inventory.main:app", host=config.HOST, port=config.PORT, reload=True)
