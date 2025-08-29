"""
Pydantic models for the Lead Parser API
"""
from typing import Optional, Dict, List
from enum import Enum
from pydantic import BaseModel, Field, model_validator


class JobStatus(str, Enum):
    """Job status enumeration"""
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class InputSource(BaseModel):
    """Input source configuration"""
    drive_file_id: Optional[str] = None
    url: Optional[str] = None
    
    @model_validator(mode='after')
    def validate_input_source(self):
        """Ensure exactly one input source is provided"""
        if not any([self.drive_file_id, self.url]):
            raise ValueError("Either drive_file_id or url must be provided")
        return self


class GoogleDriveConfig(BaseModel):
    """Google Drive configuration"""
    output_folder_id: str = Field(..., description="Google Drive folder ID for output files")
    use_sheets_export: bool = Field(default=True, description="Export Google Sheets as CSV")


class ParseOptions(BaseModel):
    """Parse options"""
    one_contact_per_company: bool = Field(default=False, description="Keep only one contact per company")
    source_label: Optional[str] = Field(default=None, description="Label to add to sources field")


class ParseRequest(BaseModel):
    """Parse request payload"""
    input: InputSource
    google_drive: GoogleDriveConfig
    options: ParseOptions = Field(default_factory=ParseOptions)
    callback_url: Optional[str] = None
    webhook_url: Optional[str] = Field(None, description="Zapier webhook URL to send processed CSV data")


class ParseResponse(BaseModel):
    """Parse response payload"""
    status: str
    row_count: Optional[int] = None
    parsed_csv_drive_file_id: Optional[str] = None
    report_json_drive_file_id: Optional[str] = None
    parsed_csv_link: Optional[str] = None
    report_json_link: Optional[str] = None
    job_id: Optional[str] = None
    error: Optional[str] = None
    correlation_id: Optional[str] = None


class JobResponse(BaseModel):
    """Job creation response"""
    job_id: str
    status: JobStatus
    correlation_id: str


class JobStatusResponse(BaseModel):
    """Job status response"""
    job_id: str
    status: JobStatus
    progress: Optional[float] = None
    result: Optional[ParseResponse] = None
    error: Optional[str] = None
    created_at: str
    updated_at: str
    correlation_id: str


class HeaderMapping(BaseModel):
    """Header mapping from Gemini"""
    mapping: Dict[str, str]
    unmapped: List[str] = Field(default_factory=list)


class DropRecord(BaseModel):
    """Record of dropped row"""
    row_index: int
    reason: str
    details: Optional[str] = None


class ProcessingStats(BaseModel):
    """Processing statistics"""
    valid_email_ratio: float
    linkedin_ratio: float
    phone_ratio: float
    company_ratio: float
    total_rows: int
    output_rows: int
    dropped_rows: int


class ProcessingTimings(BaseModel):
    """Processing timing information"""
    download: int
    llm: int
    normalize: int
    write: int
    total: int


class InputInfo(BaseModel):
    """Input file information"""
    rows: int
    file_type: str
    drive_file_id: Optional[str] = None
    url: Optional[str] = None


class ProcessingReport(BaseModel):
    """Complete processing report"""
    input: InputInfo
    mapping: Dict[str, str]
    unmapped_input_headers: List[str]
    drops: List[DropRecord]
    stats: ProcessingStats
    timings_ms: ProcessingTimings
    version: str
    correlation_id: str
    error: Optional[str] = None


# Target column definitions
TARGET_COLUMNS = [
    "first_name",
    "last_name", 
    "company_name",
    "email",
    "phone_number",
    "job_title",
    "linkedin_url",
    "website",
    "company_summary",
    "sources"
]
