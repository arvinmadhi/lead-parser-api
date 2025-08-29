"""
Main parsing service that orchestrates the entire parsing workflow
"""
import time
import json
import logging
import pandas as pd
import httpx
from typing import Tuple, Optional
from io import BytesIO

from app.models import (
    ParseRequest, ParseResponse, ProcessingReport, InputInfo, 
    ProcessingTimings, TARGET_COLUMNS
)
from app.services.google_drive import GoogleDriveService
from app.services.gemini import GeminiService
from app.services.data_processor import DataProcessor
from app.config import settings
from app.utils.logging import TimingLogger

logger = logging.getLogger(__name__)


class ParsingService:
    """Main service for parsing and processing lead data"""
    
    def __init__(self):
        self.drive_service = GoogleDriveService()
        self.gemini_service = GeminiService()
    
    async def parse_file(self, request: ParseRequest, correlation_id: str) -> ParseResponse:
        """
        Main parsing workflow
        
        Args:
            request: Parse request with input and options
            correlation_id: Correlation ID for tracking
            
        Returns:
            Parse response with results or error
        """
        timing_logger = TimingLogger(logger, correlation_id)
        start_time = time.time()
        
        try:
            logger.info(f"Starting parse workflow for correlation_id: {correlation_id}")
            
            # Step 1: Download input file
            download_start = time.time()
            file_content, file_name, mime_type = await self._download_input_file(request)
            download_time = int((time.time() - download_start) * 1000)
            timing_logger.log_timing("download", download_time, file_name=file_name, mime_type=mime_type)
            
            # Step 2: Load data into dataframe
            df, file_type = self._load_dataframe(file_content, file_name, mime_type)
            input_info = InputInfo(
                rows=len(df),
                file_type=file_type,
                drive_file_id=request.input.drive_file_id,
                url=request.input.url
            )
            
            logger.info(f"Loaded {len(df)} rows from {file_type} file", extra={'row_count': len(df)})
            
            # Step 3: Header mapping with Gemini
            llm_start = time.time()
            sample_rows = df.head(settings.sample_rows_for_mapping).to_dict('records')
            header_mapping = await self.gemini_service.map_headers(df.columns.tolist(), sample_rows)
            llm_time = int((time.time() - llm_start) * 1000)
            timing_logger.log_timing("llm", llm_time, 
                                   model_id=settings.gemini_model,
                                   mapped_headers=len(header_mapping.mapping),
                                   unmapped_headers=len(header_mapping.unmapped))
            
            # Step 4: Process data
            normalize_start = time.time()
            processor = DataProcessor(request.options)
            processed_df, drops, stats = processor.process_dataframe(df, header_mapping.mapping)
            normalize_time = int((time.time() - normalize_start) * 1000)
            timing_logger.log_timing("normalize", normalize_time, 
                                   output_rows=len(processed_df),
                                   dropped_rows=len(drops))
            
            # Step 5: Generate outputs
            write_start = time.time()
            csv_content = self._generate_csv(processed_df)
            
            # Create report
            total_time = int((time.time() - start_time) * 1000)
            timings = ProcessingTimings(
                download=download_time,
                llm=llm_time,
                normalize=normalize_time,
                write=0,  # Will be updated after upload
                total=total_time
            )
            
            report = ProcessingReport(
                input=input_info,
                mapping=header_mapping.mapping,
                unmapped_input_headers=header_mapping.unmapped,
                drops=drops,
                stats=stats,
                timings_ms=timings,
                version=settings.app_version,
                correlation_id=correlation_id
            )
            
            report_content = json.dumps(report.dict(), indent=2).encode('utf-8')
            
            # Step 6: Send to webhook if provided, otherwise try Google Drive upload
            if request.webhook_url:
                # Send data to webhook (Zapier)
                webhook_success = await self._send_to_webhook(
                    request.webhook_url,
                    csv_content.decode('utf-8'),
                    report.dict(),
                    file_name,
                    correlation_id
                )
                
                write_time = int((time.time() - write_start) * 1000)
                timing_logger.log_timing("webhook", write_time)
                
                if webhook_success:
                    logger.info(f"Parse workflow completed successfully with {len(processed_df)} rows - sent to webhook")
                    
                    return ParseResponse(
                        status="ok",
                        row_count=len(processed_df),
                        parsed_csv_drive_file_id=None,
                        report_json_drive_file_id=None,
                        parsed_csv_link=None,
                        report_json_link=None,
                        job_id=None
                    )
                else:
                    raise Exception("Failed to send data to webhook")
            else:
                # Original Google Drive upload logic
                csv_file_id, csv_link = await self.drive_service.upload_file(
                    csv_content, 
                    f"parsed_{file_name}.csv", 
                    request.google_drive.output_folder_id,
                    'text/csv'
                )
                
                report_file_id, report_link = await self.drive_service.upload_file(
                    report_content,
                    f"report_{file_name}.json",
                    request.google_drive.output_folder_id,
                    'application/json'
                )
                
                write_time = int((time.time() - write_start) * 1000)
                timing_logger.log_timing("write", write_time, 
                                       csv_file_id=csv_file_id,
                                       report_file_id=report_file_id)
                
                # Update timings in report and re-upload
                report.timings_ms.write = write_time
                report.timings_ms.total = int((time.time() - start_time) * 1000)
                
                updated_report_content = json.dumps(report.dict(), indent=2).encode('utf-8')
                await self.drive_service.upload_file(
                    updated_report_content,
                    f"report_{file_name}.json",
                    request.google_drive.output_folder_id,
                    'application/json'
                )
                
                logger.info(f"Parse workflow completed successfully with {len(processed_df)} rows")
                
                return ParseResponse(
                    status="ok",
                    row_count=len(processed_df),
                    parsed_csv_drive_file_id=csv_file_id,
                    report_json_drive_file_id=report_file_id,
                    parsed_csv_link=csv_link,
                    report_json_link=report_link,
                    job_id=None
                )
            
        except Exception as e:
            logger.error(f"Parse workflow failed: {e}")
            
            # Try to upload error report
            try:
                error_report = ProcessingReport(
                    input=InputInfo(rows=0, file_type="unknown"),
                    mapping={},
                    unmapped_input_headers=[],
                    drops=[],
                    stats=None,
                    timings_ms=ProcessingTimings(download=0, llm=0, normalize=0, write=0, total=0),
                    version=settings.app_version,
                    correlation_id=correlation_id,
                    error=str(e)
                )
                
                error_content = json.dumps(error_report.dict(), indent=2).encode('utf-8')
                await self.drive_service.upload_file(
                    error_content,
                    f"error_report_{correlation_id}.json",
                    request.google_drive.output_folder_id,
                    'application/json'
                )
            except Exception as upload_error:
                logger.error(f"Failed to upload error report: {upload_error}")
            
            raise
    
    async def _download_input_file(self, request: ParseRequest) -> Tuple[bytes, str, str]:
        """Download input file from Google Drive or URL"""
        
        if request.input.drive_file_id:
            return await self.drive_service.download_file(request.input.drive_file_id)
        elif request.input.url:
            # TODO: Implement URL download
            raise NotImplementedError("URL download not yet implemented")
        else:
            raise ValueError("No input source specified")
    
    def _load_dataframe(self, content: bytes, filename: str, mime_type: str) -> Tuple[pd.DataFrame, str]:
        """Load content into pandas DataFrame"""
        
        file_io = BytesIO(content)
        
        if mime_type == 'text/csv' or filename.lower().endswith('.csv'):
            try:
                df = pd.read_csv(file_io, encoding='utf-8')
                return df, 'csv'
            except UnicodeDecodeError:
                file_io.seek(0)
                df = pd.read_csv(file_io, encoding='latin-1')
                return df, 'csv'
        
        elif mime_type in ['application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', 
                          'application/vnd.ms-excel'] or filename.lower().endswith(('.xlsx', '.xls')):
            df = pd.read_excel(file_io, engine='openpyxl')
            return df, 'xlsx'
        
        else:
            raise ValueError(f"Unsupported file type: {mime_type}")
    
    def _generate_csv(self, df: pd.DataFrame) -> bytes:
        """Generate CSV content from dataframe"""
        
        # Ensure proper column order
        df_ordered = df[TARGET_COLUMNS]
        
        # Convert to CSV
        csv_content = df_ordered.to_csv(index=False, encoding='utf-8')
        return csv_content.encode('utf-8')
    
    async def _send_to_webhook(self, webhook_url: str, csv_content: str, report_data: dict, 
                             file_name: str, correlation_id: str) -> bool:
        """Send processed data to webhook (Zapier)"""
        try:
            # Calculate payload size
            csv_size_bytes = len(csv_content.encode('utf-8'))
            csv_size_mb = csv_size_bytes / (1024 * 1024)
            
            logger.info(f"Sending webhook data - CSV size: {csv_size_mb:.2f} MB ({csv_size_bytes:,} bytes)")
            
            # Check size limits (most webhooks support 1-10MB)
            if csv_size_mb > 5:  # Conservative 5MB limit
                logger.warning(f"CSV size ({csv_size_mb:.2f} MB) may exceed webhook limits")
            
            # Parse CSV into structured leads array
            leads = self._parse_csv_to_leads(csv_content)
            
            # Prepare webhook payload with both formats
            payload = {
                "status": "success",
                "source_file": file_name,
                "row_count": report_data.get("stats", {}).get("output_rows", 0),
                "leads": leads,  # ✨ NEW: Structured lead objects
                "csv_data": csv_content,  # Keep original for compatibility
                "header_mapping": {
                    "mapped": report_data.get("mapping", {}).get("mapping", {}),
                    "unmapped": report_data.get("mapping", {}).get("unmapped", [])
                },  # ✨ NEW: Show what headers were mapped
                "report": report_data,
                "correlation_id": correlation_id,
                "timestamp": time.time()
            }
            
            # Send to webhook with timeout
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    webhook_url,
                    json=payload,
                    headers={
                        "Content-Type": "application/json",
                        "User-Agent": f"LeadParser/{settings.app_version}"
                    }
                )
                
                if response.status_code == 200:
                    logger.info(f"Webhook sent successfully to {webhook_url} - Response: {response.status_code}")
                    return True
                else:
                    logger.error(f"Webhook failed - Status: {response.status_code}, Response: {response.text}")
                    return False
                    
        except httpx.TimeoutException:
            logger.error(f"Webhook timeout sending to {webhook_url}")
            return False
        except Exception as e:
            logger.error(f"Webhook error sending to {webhook_url}: {e}")
            return False
    
    def _parse_csv_to_leads(self, csv_content: str) -> list:
        """Parse CSV content into structured lead objects"""
        try:
            lines = csv_content.strip().split('\n')
            if len(lines) < 2:
                return []
            
            headers = [h.strip() for h in lines[0].split(',')]
            leads = []
            
            for line in lines[1:]:
                if line.strip():
                    values = [v.strip() for v in line.split(',')]
                    lead = {}
                    for i, header in enumerate(headers):
                        lead[header] = values[i] if i < len(values) else ""
                    leads.append(lead)
            
            return leads
        except Exception as e:
            logger.error(f"Failed to parse CSV to leads: {e}")
            return []
