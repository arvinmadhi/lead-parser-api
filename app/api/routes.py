"""
API routes for the Lead Parser
"""
import logging
from typing import Dict, Any
from fastapi import APIRouter, HTTPException, Request, Depends

from app.models import (
    ParseRequest, ParseResponse, JobResponse, JobStatusResponse
)
from app.services.parser import ParsingService
from app.services.job_manager import job_manager
from app.config import settings

logger = logging.getLogger(__name__)

router = APIRouter()


def get_correlation_id(request: Request) -> str:
    """Get correlation ID from request"""
    return getattr(request.state, 'correlation_id', 'unknown')


@router.post("/parse", response_model=ParseResponse)
async def parse_file(
    request_data: ParseRequest,
    request: Request,
    correlation_id: str = Depends(get_correlation_id)
):
    """
    Synchronous file parsing endpoint for small/medium files
    """
    try:
        logger.info("Parse request received")
        
        # Initialize parsing service
        parsing_service = ParsingService()
        
        # Process the file
        result = await parsing_service.parse_file(request_data, correlation_id)
        
        return result
        
    except TimeoutError:
        logger.error("Gemini API timeout")
        raise HTTPException(
            status_code=408,
            detail={
                "error": "Gemini API timeout",
                "message": f"Request timed out after {settings.gemini_timeout} seconds",
                "correlation_id": correlation_id
            }
        )
    
    except ValueError as e:
        error_msg = str(e)
        logger.error(f"Validation error: {error_msg}")
        
        # Check for specific error types
        if "access denied" in error_msg.lower():
            service_account_email = "your-service-account@project.iam.gserviceaccount.com"
            try:
                from app.services.google_drive import GoogleDriveService
                drive_service = GoogleDriveService()
                service_account_email = drive_service.get_service_account_email()
            except Exception:
                pass
            
            if "file" in error_msg.lower():
                raise HTTPException(
                    status_code=403,
                    detail={
                        "error": "Access denied to file",
                        "message": f"Please share the file with the service account: {service_account_email}",
                        "correlation_id": correlation_id,
                        "file_id": request_data.input.drive_file_id
                    }
                )
            else:
                raise HTTPException(
                    status_code=403,
                    detail={
                        "error": "Access denied to folder", 
                        "message": f"Please share the output folder with the service account: {service_account_email}",
                        "correlation_id": correlation_id,
                        "folder_id": request_data.google_drive.output_folder_id
                    }
                )
        
        elif "not found" in error_msg.lower():
            raise HTTPException(
                status_code=400,
                detail={
                    "error": "File or folder not found",
                    "message": error_msg,
                    "correlation_id": correlation_id
                }
            )
        else:
            raise HTTPException(
                status_code=400,
                detail={
                    "error": "Invalid request",
                    "message": error_msg,
                    "correlation_id": correlation_id
                }
            )
    
    except Exception as e:
        logger.error(f"Internal server error: {e}")
        raise HTTPException(
            status_code=500,
            detail={
                "error": "Internal server error",
                "message": "An unexpected error occurred",
                "correlation_id": correlation_id
            }
        )


@router.post("/jobs", response_model=JobResponse)
async def create_job(
    request_data: ParseRequest,
    request: Request,
    correlation_id: str = Depends(get_correlation_id)
):
    """
    Create async job for large file processing
    """
    try:
        logger.info("Job creation request received")
        
        # Create job
        job_id = job_manager.create_job(request_data, correlation_id)
        
        return JobResponse(
            job_id=job_id,
            status="queued",
            correlation_id=correlation_id
        )
        
    except Exception as e:
        logger.error(f"Error creating job: {e}")
        raise HTTPException(
            status_code=500,
            detail={
                "error": "Failed to create job",
                "message": str(e),
                "correlation_id": correlation_id
            }
        )


@router.get("/jobs/{job_id}", response_model=JobStatusResponse)
async def get_job_status(
    job_id: str,
    request: Request,
    correlation_id: str = Depends(get_correlation_id)
):
    """
    Get job status and results
    """
    try:
        job_status = job_manager.get_job_status(job_id)
        
        if not job_status:
            raise HTTPException(
                status_code=404,
                detail={
                    "error": "Job not found",
                    "message": f"Job {job_id} not found",
                    "correlation_id": correlation_id
                }
            )
        
        return job_status
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting job status: {e}")
        raise HTTPException(
            status_code=500,
            detail={
                "error": "Failed to get job status",
                "message": str(e),
                "correlation_id": correlation_id
            }
        )


@router.get("/jobs", response_model=Dict[str, Any])
async def list_jobs(
    request: Request,
    correlation_id: str = Depends(get_correlation_id)
):
    """
    List all jobs (debugging endpoint)
    """
    try:
        jobs = job_manager.get_all_jobs()
        return {
            "jobs": jobs,
            "total": len(jobs)
        }
        
    except Exception as e:
        logger.error(f"Error listing jobs: {e}")
        raise HTTPException(
            status_code=500,
            detail={
                "error": "Failed to list jobs",
                "message": str(e),
                "correlation_id": correlation_id
            }
        )


@router.get("/debug/headers/{file_id}")
async def debug_file_headers(
    file_id: str,
    correlation_id: str = Depends(get_correlation_id)
):
    """
    Debug endpoint to see original headers and mapping results
    """
    try:
        logger.info(f"Debug headers request for file {file_id}")
        
        from app.services.google_drive import GoogleDriveService
        from app.services.gemini import GeminiService
        from io import BytesIO
        import pandas as pd
        
        drive_service = GoogleDriveService()
        gemini_service = GeminiService()
        
        # Download and load file
        file_content, file_name, mime_type = await drive_service.download_file(file_id)
        
        # Load data to see headers
        if mime_type == 'text/csv':
            df = pd.read_csv(BytesIO(file_content))
        elif mime_type == 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet':
            df = pd.read_excel(BytesIO(file_content))
        else:
            df = pd.read_csv(BytesIO(file_content))  # Try CSV as fallback
        
        original_headers = df.columns.tolist()
        
        # Get sample data (first 3 rows)
        sample_data = df.head(3).to_dict('records')
        
        # Map headers using Gemini
        header_mapping = await gemini_service.map_headers(original_headers, correlation_id)
        
        return {
            "status": "success",
            "file_name": file_name,
            "mime_type": mime_type,
            "original_headers": original_headers,
            "header_mapping": header_mapping.mapping,
            "unmapped_headers": header_mapping.unmapped,
            "sample_data": sample_data,
            "correlation_id": correlation_id
        }
        
    except Exception as e:
        logger.error(f"Debug headers failed: {e}")
        return {
            "status": "error",
            "message": str(e),
            "correlation_id": correlation_id
        }


@router.get("/debug/service-account")
async def get_service_account_info(request: Request):
    """
    Debug endpoint to get service account email
    """
    try:
        from app.services.google_drive import GoogleDriveService
        drive_service = GoogleDriveService()
        email = drive_service.get_service_account_email()
        
        return {
            "service_account_email": email,
            "instructions": f"Share your Google Drive files and folders with: {email}",
            "test_folders": {
                "input_folder_id": settings.test_input_folder_id,
                "output_folder_id": settings.test_output_folder_id
            }
        }
        
    except Exception as e:
        logger.error(f"Error getting service account info: {e}")
        raise HTTPException(
            status_code=500,
            detail={
                "error": "Failed to get service account info",
                "message": str(e)
            }
        )


@router.post("/test/upload")
async def test_upload(
    request: Request,
    correlation_id: str = Depends(get_correlation_id)
):
    """
    Test endpoint to upload a minimal file and see detailed Google Drive API errors
    """
    try:
        from app.services.google_drive import GoogleDriveService
        
        drive_service = GoogleDriveService()
        
        # Create minimal test file
        test_content = b"test,content\n1,2"
        test_filename = "test_upload.csv"
        
        # Try uploading to the input folder (which we know has permissions)
        file_id, share_link = await drive_service.upload_file(
            test_content,
            test_filename,
            settings.test_input_folder_id,  # Use input folder for test
            'text/csv'
        )
        
        return {
            "status": "success",
            "message": "Upload test successful!",
            "file_id": file_id,
            "share_link": share_link,
            "folder_id": settings.test_input_folder_id,
            "correlation_id": correlation_id
        }
        
    except Exception as e:
        logger.error(f"Upload test failed: {e}")
        return {
            "status": "error",
            "message": str(e),
            "correlation_id": correlation_id
        }


@router.get("/debug/list-files")
async def list_service_account_files(
    request: Request,
    correlation_id: str = Depends(get_correlation_id)
):
    """
    List files visible to the service account to debug storage issues
    """
    try:
        from app.services.google_drive import GoogleDriveService
        
        drive_service = GoogleDriveService()
        
        # List files in service account's "My Drive"
        try:
            results = drive_service.service.files().list(
                pageSize=50,
                fields="nextPageToken, files(id, name, size, mimeType, parents, createdTime)"
            ).execute()
            
            files = results.get('files', [])
            
            return {
                "status": "success",
                "message": f"Found {len(files)} files visible to service account",
                "files": files,
                "correlation_id": correlation_id
            }
            
        except Exception as api_error:
            return {
                "status": "error", 
                "message": f"API Error: {str(api_error)}",
                "correlation_id": correlation_id
            }
        
    except Exception as e:
        logger.error(f"List files failed: {e}")
        return {
            "status": "error",
            "message": str(e),
            "correlation_id": correlation_id
        }


@router.post("/test/webhook/{file_id}")
async def test_webhook_parse(
    file_id: str,
    webhook_url: str,
    request: Request,
    one_contact_per_company: bool = False,
    source_label: str = "Webhook Test",
    correlation_id: str = Depends(get_correlation_id)
):
    """
    Test endpoint to parse a file and send results to a webhook (Zapier)
    """
    try:
        logger.info(f"Webhook test parse request for file {file_id} -> {webhook_url}")
        
        # Create request with webhook
        request_data = ParseRequest(
            input={"drive_file_id": file_id},
            google_drive={"output_folder_id": settings.test_output_folder_id},
            options={
                "one_contact_per_company": one_contact_per_company,
                "source_label": source_label
            },
            webhook_url=webhook_url
        )
        
        # Initialize parsing service
        parsing_service = ParsingService()
        
        # Process the file and send to webhook
        result = await parsing_service.parse_file(request_data, correlation_id)
        
        return {
            "status": "success",
            "message": "File processed and sent to webhook successfully!",
            "webhook_url": webhook_url,
            "row_count": result.row_count,
            "correlation_id": correlation_id
        }
        
    except Exception as e:
        logger.error(f"Webhook test failed: {e}")
        return {
            "status": "error",
            "message": str(e),
            "webhook_url": webhook_url,
            "correlation_id": correlation_id
        }


@router.post("/test/csv/{file_id}")
async def test_parse_to_csv(
    file_id: str,
    request: Request,
    one_contact_per_company: bool = False,
    source_label: str = "CSV Export",
    correlation_id: str = Depends(get_correlation_id)
):
    """
    Test endpoint to parse a file and return a downloadable CSV file
    """
    try:
        logger.info(f"CSV export parse request for file {file_id}")
        
        # Create request
        request_data = ParseRequest(
            input={"drive_file_id": file_id},
            google_drive={"output_folder_id": settings.test_output_folder_id},
            options={
                "one_contact_per_company": one_contact_per_company,
                "source_label": source_label
            }
        )
        
        # Initialize services
        from app.services.google_drive import GoogleDriveService
        from app.services.gemini import GeminiService
        from app.services.data_processor import DataProcessor
        from io import BytesIO
        import pandas as pd
        
        drive_service = GoogleDriveService()
        gemini_service = GeminiService()
        data_processor = DataProcessor(request_data.options)
        
        # Download and load file
        file_content, file_name, mime_type = await drive_service.download_file(file_id)
        
        # Load data
        if mime_type == 'text/csv':
            df = pd.read_csv(BytesIO(file_content))
        elif mime_type == 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet':
            df = pd.read_excel(BytesIO(file_content))
        else:
            df = pd.read_csv(BytesIO(file_content))  # Try CSV as fallback
            
        # Map headers using Gemini
        header_mapping = await gemini_service.map_headers(df.columns.tolist(), correlation_id)
        
        # Apply mapping and process
        processed_df, drops, stats = data_processor.process_dataframe(df, header_mapping.mapping)
        
        # Generate CSV content
        csv_content = processed_df.to_csv(index=False)
        
        # Return as downloadable file
        from fastapi.responses import Response
        
        return Response(
            content=csv_content,
            media_type="text/csv",
            headers={
                "Content-Disposition": f"attachment; filename=parsed_{file_name}.csv",
                "Content-Length": str(len(csv_content))
            }
        )
        
    except Exception as e:
        logger.error(f"CSV export failed: {e}")
        return {
            "status": "error",
            "message": str(e),
            "correlation_id": correlation_id
        }


