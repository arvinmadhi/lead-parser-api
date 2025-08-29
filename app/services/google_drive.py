"""
Google Drive service for file operations
"""
import os
import io
import logging
from typing import Optional, Tuple, BinaryIO
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload
from google.auth.transport.requests import Request
from google.oauth2 import service_account
from googleapiclient.errors import HttpError

from app.config import settings

logger = logging.getLogger(__name__)


class GoogleDriveService:
    """Google Drive service for file operations"""
    
    def __init__(self):
        self.service = None
        self._initialize_service()
    
    def _initialize_service(self):
        """Initialize Google Drive service with service account credentials"""
        try:
            if not settings.google_application_credentials:
                raise ValueError("GOOGLE_APPLICATION_CREDENTIALS environment variable not set")
            
            if not os.path.exists(settings.google_application_credentials):
                raise ValueError(f"Credentials file not found: {settings.google_application_credentials}")
            
            credentials = service_account.Credentials.from_service_account_file(
                settings.google_application_credentials,
                scopes=['https://www.googleapis.com/auth/drive']
            )
            
            self.service = build('drive', 'v3', credentials=credentials)
            logger.info("Google Drive service initialized successfully")
            
        except Exception as e:
            logger.error(f"Failed to initialize Google Drive service: {e}")
            raise
    
    async def download_file(self, file_id: str) -> Tuple[bytes, str, str]:
        """
        Download a file from Google Drive
        
        Args:
            file_id: Google Drive file ID
            
        Returns:
            Tuple of (file_content, file_name, mime_type)
        """
        try:
            # Get file metadata
            file_metadata = self.service.files().get(fileId=file_id).execute()
            file_name = file_metadata['name']
            mime_type = file_metadata['mimeType']
            
            logger.info(f"Downloading file: {file_name} (type: {mime_type})")
            
            # Handle Google Sheets export
            if mime_type == 'application/vnd.google-apps.spreadsheet':
                # Always export as CSV for Google Sheets
                request = self.service.files().export_media(
                    fileId=file_id,
                    mimeType='text/csv'
                )
                mime_type = 'text/csv'
                file_name = file_name.replace('.xlsx', '.csv').replace('.xls', '.csv')
                if not file_name.endswith('.csv'):
                    file_name += '.csv'
            else:
                # Regular file download
                request = self.service.files().get_media(fileId=file_id)
            
            # Download the file
            file_io = io.BytesIO()
            downloader = MediaIoBaseDownload(file_io, request)
            
            done = False
            while done is False:
                status, done = downloader.next_chunk()
            
            file_content = file_io.getvalue()
            logger.info(f"Successfully downloaded {len(file_content)} bytes")
            
            return file_content, file_name, mime_type
            
        except HttpError as e:
            if e.resp.status == 403:
                logger.error(f"Access denied to file {file_id}. Ensure the file is shared with the service account.")
                raise ValueError(f"Access denied to file {file_id}. Please share the file with the service account.")
            elif e.resp.status == 404:
                logger.error(f"File {file_id} not found")
                raise ValueError(f"File {file_id} not found")
            else:
                logger.error(f"HTTP error downloading file {file_id}: {e}")
                raise
        except Exception as e:
            logger.error(f"Error downloading file {file_id}: {e}")
            raise
    
    async def upload_file(self, content: bytes, filename: str, folder_id: str, mime_type: str = 'text/csv') -> Tuple[str, str]:
        """
        Upload a file to Google Drive
        
        Args:
            content: File content as bytes
            filename: Name for the uploaded file
            folder_id: Google Drive folder ID to upload to
            mime_type: MIME type of the file
            
        Returns:
            Tuple of (file_id, share_link)
        """
        try:
            # Create file metadata
            file_metadata = {
                'name': filename,
                'parents': [folder_id]
            }
            
            # Create media upload
            media = MediaIoBaseUpload(
                io.BytesIO(content),
                mimetype=mime_type,
                resumable=True
            )
            
            # Upload the file
            file = self.service.files().create(
                body=file_metadata,
                media_body=media,
                fields='id'
            ).execute()
            
            file_id = file.get('id')
            
            # Create share link
            share_link = f"https://drive.google.com/file/d/{file_id}/view"
            
            logger.info(f"Successfully uploaded file {filename} with ID {file_id}")
            
            return file_id, share_link
            
        except HttpError as e:
            # Log detailed error information
            error_content = e.content.decode('utf-8') if e.content else 'No error content'
            logger.error(f"Google Drive API Error - Status: {e.resp.status}, Reason: {e.resp.reason}")
            logger.error(f"Error content: {error_content}")
            logger.error(f"Error details: {e.error_details if hasattr(e, 'error_details') else 'No details'}")
            
            if e.resp.status == 403:
                if 'storageQuotaExceeded' in error_content:
                    logger.error(f"Storage quota exceeded for folder {folder_id}")
                    raise ValueError(f"Storage quota exceeded. This may be a service account storage limit issue.")
                else:
                    logger.error(f"Access denied to folder {folder_id}. Ensure the folder is shared with the service account.")
                    raise ValueError(f"Access denied to folder {folder_id}. Please share the folder with the service account.")
            elif e.resp.status == 404:
                logger.error(f"Folder {folder_id} not found")
                raise ValueError(f"Folder {folder_id} not found")
            else:
                logger.error(f"HTTP error uploading file to folder {folder_id}: {e}")
                raise
        except Exception as e:
            logger.error(f"Error uploading file to folder {folder_id}: {e}")
            raise
    
    def get_service_account_email(self) -> str:
        """Get the service account email for sharing instructions"""
        try:
            credentials = service_account.Credentials.from_service_account_file(
                settings.google_application_credentials
            )
            return credentials.service_account_email
        except Exception as e:
            logger.error(f"Error getting service account email: {e}")
            return "unknown@serviceaccount.com"
