"""
Lead Parser API - Main application entry point
"""
import logging
import uuid
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

from app.api.routes import router
from app.utils.logging import setup_logging


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager"""
    # Startup
    setup_logging()
    logging.info("Lead Parser API starting up...")
    yield
    # Shutdown
    logging.info("Lead Parser API shutting down...")


app = FastAPI(
    title="Lead Parser API",
    description="Convert messy CSV/XLSX/Google Sheets into clean CSV with normalized contact data",
    version="v1.0.0",
    lifespan=lifespan
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def add_correlation_id(request: Request, call_next):
    """Add correlation ID to each request"""
    correlation_id = str(uuid.uuid4())
    request.state.correlation_id = correlation_id
    
    # Add to logging context
    old_factory = logging.getLogRecordFactory()
    def record_factory(*args, **kwargs):
        record = old_factory(*args, **kwargs)
        record.correlation_id = correlation_id
        return record
    logging.setLogRecordFactory(record_factory)
    
    response = await call_next(request)
    response.headers["X-Correlation-ID"] = correlation_id
    
    # Restore original factory
    logging.setLogRecordFactory(old_factory)
    return response


# Include API routes
app.include_router(router)


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "ok", "version": "v1.0.0"}


if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )
