# Lead Parser API

Convert messy CSV/XLSX/Google Sheets into clean CSV with exactly 10 normalized columns:
`first_name`, `last_name`, `company_name`, `email`, `phone_number`, `job_title`, `linkedin_url`, `website`, `company_summary`, `sources`

## Features

- **Smart Header Mapping**: Uses Gemini 2.5 Flash to intelligently map arbitrary input headers to target columns
- **Data Normalization**: Cleans and standardizes all fields according to best practices
- **Google Drive Integration**: Seamlessly download input files and upload results
- **Async Processing**: Handle both sync (small files) and async (large files) workflows
- **Deduplication**: Optional one-contact-per-company filtering
- **Comprehensive Reporting**: Detailed JSON reports with statistics and processing info

## Quick Start

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Setup Environment Variables

Create a `.env` file:

```bash
# Google Drive Service Account
GOOGLE_APPLICATION_CREDENTIALS=/path/to/your/service-account-key.json

# Gemini API
GEMINI_API_KEY=your_gemini_api_key_here
```

### 3. Setup Google Drive

1. Create a Google Cloud Project
2. Enable the Google Drive API
3. Create a Service Account and download the JSON key
4. Share your Google Drive files/folders with the service account email

### 4. Run the API

```bash
python main.py
```

The API will be available at `http://localhost:8000`

## API Endpoints

### POST /parse (Sync)
Process small/medium files synchronously.

```json
{
  "input": { "drive_file_id": "1AbC...xyz" },
  "google_drive": { "output_folder_id": "1OutputFolderId" },
  "options": { 
    "one_contact_per_company": true, 
    "source_label": "Import 2025-01-15" 
  }
}
```

### POST /jobs (Async)
Create async job for large files.

### GET /jobs/{job_id}
Check job status and get results.

### GET /health
Health check endpoint.

### GET /debug/service-account
Get service account email for sharing setup.

## Output Format

**parsed.csv**: Clean CSV with exactly 10 columns, no empty rows
**report.json**: Processing statistics, mappings, and timing information

## Error Handling

- **400**: Invalid request (missing file)
- **401/403**: Access denied (share with service account)
- **408**: Gemini timeout
- **422**: Bad LLM mapping
- **500**: Internal server error

## Configuration

All settings can be configured via environment variables:

- `GEMINI_TIMEOUT`: Timeout for Gemini API calls (default: 60s)
- `MAX_FILE_SIZE_MB`: Maximum file size (default: 100MB)
- `MAX_ROWS_FOR_SYNC`: Max rows for sync processing (default: 10,000)
- `DEBUG`: Enable debug logging

## Development

The project structure:

```
app/
├── api/           # FastAPI routes
├── models.py      # Pydantic models
├── services/      # Business logic
│   ├── google_drive.py
│   ├── gemini.py
│   ├── data_processor.py
│   ├── parser.py
│   └── job_manager.py
└── utils/         # Utilities
    └── logging.py
```

## Deployment to Railway

### Prerequisites
1. Railway account at [railway.app](https://railway.app)
2. Railway CLI: `npm install -g @railway/cli`
3. Google Cloud Project with Drive API enabled
4. Gemini API key

### Deploy Steps

1. **Prepare the codebase:**
   ```bash
   # Files are already configured for Railway deployment
   # railway.json and nixpacks.toml are included
   ```

2. **Push to GitHub first:**
   ```bash
   git add .
   git commit -m "Initial commit"
   git branch -M main
   git remote add origin https://github.com/yourusername/your-repo-name.git
   git push -u origin main
   ```

3. **Deploy to Railway:**
   ```bash
   railway login
   railway init
   railway deploy
   ```

4. **Set Environment Variables in Railway:**
   - `GOOGLE_APPLICATION_CREDENTIALS_JSON`: Contents of your service-account-key.json file
   - `GEMINI_API_KEY`: Your Gemini API key
   - `DEBUG`: false
   - `GEMINI_TIMEOUT`: 60
   - `MAX_FILE_SIZE_MB`: 100
   - `MAX_ROWS_FOR_SYNC`: 10000

### Alternative: GitHub Integration
1. Push code to GitHub
2. Connect Railway to your GitHub repo in the Railway dashboard
3. Set environment variables
4. Deploy automatically on pushes

## License

See LICENSE file for details.
