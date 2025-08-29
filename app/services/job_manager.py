"""
Job management service for async processing
"""
import asyncio
import json
import logging
import uuid
from datetime import datetime, timedelta
from typing import Dict, Optional, Any
from dataclasses import dataclass

from app.models import JobStatus, ParseRequest, ParseResponse, JobStatusResponse
from app.services.parser import ParsingService

logger = logging.getLogger(__name__)


@dataclass
class Job:
    """Job data structure"""
    job_id: str
    status: JobStatus
    request: ParseRequest
    correlation_id: str
    created_at: datetime
    updated_at: datetime
    progress: float = 0.0
    result: Optional[ParseResponse] = None
    error: Optional[str] = None
    callback_url: Optional[str] = None


class JobManager:
    """Manager for async job processing"""
    
    def __init__(self):
        self.jobs: Dict[str, Job] = {}
        self.parsing_service = ParsingService()
        self._cleanup_task: Optional[asyncio.Task] = None
    
    def _start_cleanup_task(self):
        """Start background task for job cleanup"""
        try:
            if self._cleanup_task is None or self._cleanup_task.done():
                self._cleanup_task = asyncio.create_task(self._cleanup_old_jobs())
        except RuntimeError:
            # No event loop running, that's okay
            pass
    
    async def _cleanup_old_jobs(self):
        """Background task to clean up old jobs"""
        while True:
            try:
                cutoff_time = datetime.utcnow() - timedelta(hours=24)  # 24 hours as specified
                jobs_to_remove = []
                
                for job_id, job in self.jobs.items():
                    if job.updated_at < cutoff_time and job.status in [JobStatus.COMPLETED, JobStatus.FAILED]:
                        jobs_to_remove.append(job_id)
                
                for job_id in jobs_to_remove:
                    del self.jobs[job_id]
                    logger.info(f"Cleaned up old job: {job_id}")
                
                # Sleep for 1 hour before next cleanup
                await asyncio.sleep(3600)
                
            except Exception as e:
                logger.error(f"Error in job cleanup: {e}")
                await asyncio.sleep(3600)  # Sleep and retry
    
    def create_job(self, request: ParseRequest, correlation_id: str) -> str:
        """
        Create a new async job
        
        Args:
            request: Parse request
            correlation_id: Correlation ID for tracking
            
        Returns:
            Job ID
        """
        job_id = str(uuid.uuid4())
        now = datetime.utcnow()
        
        job = Job(
            job_id=job_id,
            status=JobStatus.QUEUED,
            request=request,
            correlation_id=correlation_id,
            created_at=now,
            updated_at=now,
            callback_url=request.callback_url
        )
        
        self.jobs[job_id] = job
        
        # Start cleanup task if not running
        self._start_cleanup_task()
        
        # Start processing in background
        asyncio.create_task(self._process_job(job_id))
        
        logger.info(f"Created job {job_id}")
        
        return job_id
    
    async def _process_job(self, job_id: str):
        """Process a job in the background"""
        try:
            job = self.jobs.get(job_id)
            if not job:
                logger.error(f"Job {job_id} not found")
                return
            
            # Update status to processing
            job.status = JobStatus.PROCESSING
            job.updated_at = datetime.utcnow()
            job.progress = 0.1
            
            logger.info(f"Starting job processing: {job_id}")
            
            # Process the file
            try:
                result = await self.parsing_service.parse_file(job.request, job.correlation_id)
                
                # Update job with success
                job.status = JobStatus.COMPLETED
                job.result = result
                job.progress = 1.0
                job.updated_at = datetime.utcnow()
                
                logger.info(f"Job completed successfully: {job_id}")
                
            except Exception as e:
                # Update job with error
                job.status = JobStatus.FAILED
                job.error = str(e)
                job.updated_at = datetime.utcnow()
                
                logger.error(f"Job failed: {job_id} - {e}")
            
            # Send callback if configured
            if job.callback_url:
                await self._send_callback(job)
                
        except Exception as e:
            logger.error(f"Error processing job {job_id}: {e}")
            
            # Update job with critical error
            if job_id in self.jobs:
                job = self.jobs[job_id]
                job.status = JobStatus.FAILED
                job.error = f"Critical error: {e}"
                job.updated_at = datetime.utcnow()
    
    async def _send_callback(self, job: Job):
        """Send callback notification (placeholder for now)"""
        try:
            # TODO: Implement HTTP callback
            logger.info(f"Would send callback for job {job.job_id} to {job.callback_url}")
            
            # For now, just log the callback payload
            callback_payload = {
                "job_id": job.job_id,
                "status": job.status.value,
                "correlation_id": job.correlation_id,
                "result": job.result.dict() if job.result else None,
                "error": job.error
            }
            
            logger.info(f"Callback payload: {json.dumps(callback_payload)}")
            
        except Exception as e:
            logger.error(f"Error sending callback for job {job.job_id}: {e}")
    
    def get_job_status(self, job_id: str) -> Optional[JobStatusResponse]:
        """Get job status"""
        job = self.jobs.get(job_id)
        if not job:
            return None
        
        return JobStatusResponse(
            job_id=job.job_id,
            status=job.status,
            progress=job.progress,
            result=job.result,
            error=job.error,
            created_at=job.created_at.isoformat(),
            updated_at=job.updated_at.isoformat(),
            correlation_id=job.correlation_id
        )
    
    def get_all_jobs(self) -> Dict[str, Dict[str, Any]]:
        """Get all jobs (for debugging)"""
        return {
            job_id: {
                "status": job.status.value,
                "created_at": job.created_at.isoformat(),
                "updated_at": job.updated_at.isoformat(),
                "progress": job.progress,
                "correlation_id": job.correlation_id,
                "has_result": job.result is not None,
                "error": job.error
            }
            for job_id, job in self.jobs.items()
        }


# Global job manager instance
job_manager = JobManager()
