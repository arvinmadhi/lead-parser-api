"""
Configuration settings for the Lead Parser API
"""
import os
from typing import Optional
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings"""
    
    # Google Drive settings
    google_application_credentials: str = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "")
    
    # Gemini API settings
    gemini_api_key: str = os.getenv("GEMINI_API_KEY", "")
    gemini_model: str = "gemini-2.5-flash"
    gemini_timeout: int = 60
    
    # Application settings
    app_name: str = "Lead Parser API"
    app_version: str = "parser-v1.0.0"
    debug: bool = False
    
    # File processing limits
    max_file_size_mb: int = 100
    max_rows_for_sync: int = 10000
    sample_rows_for_mapping: int = 25
    
    # Async job settings
    job_cleanup_hours: int = 24
    
    # Test folder IDs (hardcoded for convenience)
    test_input_folder_id: str = "1LBc_zryVKTVAHBEexzypvzTdUQFPovDG"
    test_output_folder_id: str = "1LBc_zryVKTVAHBEexzypvzTdUQFPovDG"  # Use same folder as input
    
    # Service account limitation: Cannot upload files to regular Drive
    # Solution: Return processed data via API response
    
    class Config:
        env_file = ".env"
        case_sensitive = False


settings = Settings()
