"""
Gemini service for header mapping using Gemini 2.5 Flash
"""
import json
import logging
import asyncio
from typing import List, Dict, Any, Tuple
import google.generativeai as genai
from google.generativeai.types import HarmCategory, HarmBlockThreshold

from app.config import settings
from app.models import HeaderMapping, TARGET_COLUMNS

logger = logging.getLogger(__name__)


class GeminiService:
    """Gemini service for intelligent header mapping"""
    
    def __init__(self):
        self.model = None
        self._initialize_service()
    
    def _initialize_service(self):
        """Initialize Gemini service"""
        try:
            if not settings.gemini_api_key:
                raise ValueError("GEMINI_API_KEY environment variable not set")
            
            genai.configure(api_key=settings.gemini_api_key)
            
            self.model = genai.GenerativeModel(
                model_name=settings.gemini_model,
                generation_config={
                    "temperature": 0,
                    "top_p": 1,
                    "top_k": 1,
                    "max_output_tokens": 8192,
                }
            )
            
            logger.info(f"Gemini service initialized with model: {settings.gemini_model}")
            
        except Exception as e:
            logger.error(f"Failed to initialize Gemini service: {e}")
            raise
    
    async def map_headers(self, input_headers: List[str], sample_rows: List[Dict[str, Any]]) -> HeaderMapping:
        """
        Map input headers to target headers using Gemini 2.5 Flash
        
        Args:
            input_headers: List of input column headers
            sample_rows: Sample rows for context (max 25)
            
        Returns:
            HeaderMapping object with mapping and unmapped headers
        """
        try:
            # Limit sample rows as specified
            limited_samples = sample_rows[:settings.sample_rows_for_mapping]
            
            # Create the prompt
            prompt = self._create_mapping_prompt(input_headers, limited_samples)
            
            logger.info(f"Sending header mapping request to {settings.gemini_model}")
            logger.debug(f"Input headers: {input_headers}")
            
            # Make the API call with timeout
            response = await asyncio.wait_for(
                self._call_gemini(prompt),
                timeout=settings.gemini_timeout
            )
            
            # Parse the response
            mapping_result = self._parse_mapping_response(response, input_headers)
            
            logger.info(f"Successfully mapped {len(mapping_result.mapping)} headers")
            logger.debug(f"Mapping: {mapping_result.mapping}")
            logger.debug(f"Unmapped: {mapping_result.unmapped}")
            
            return mapping_result
            
        except asyncio.TimeoutError:
            logger.error(f"Gemini API call timed out after {settings.gemini_timeout} seconds")
            raise TimeoutError(f"Gemini API call timed out after {settings.gemini_timeout} seconds")
        except Exception as e:
            logger.error(f"Error in header mapping: {e}")
            raise
    
    def _create_mapping_prompt(self, input_headers: List[str], sample_rows: List[Dict[str, Any]]) -> str:
        """Create an intelligent, dynamic prompt for header mapping"""
        
        # Format sample data for detailed analysis
        sample_data_str = ""
        if sample_rows:
            sample_data_str = "\n\nSAMPLE DATA FOR ANALYSIS:\n"
            for i, row in enumerate(sample_rows[:3], 1):  # Show first 3 rows
                sample_data_str += f"Row {i}:\n"
                for header, value in row.items():
                    sample_data_str += f"  '{header}': '{value}'\n"
                sample_data_str += "\n"
        
        prompt = f"""You are an expert data parser. Analyze this CSV data and intelligently map columns to extract lead information.

INPUT HEADERS: {input_headers}

TARGET FIELDS (REQUIRED):
- first_name: Person's first/given name
- last_name: Person's surname/family name  
- company_name: Company/organization name
- email: Email address
- phone_number: Phone/mobile number
- job_title: Job title/position
- linkedin_url: LinkedIn profile URL
- website: Company website URL
- company_summary: Company description/summary
- sources: Data source information

{sample_data_str}

INTELLIGENT PARSING INSTRUCTIONS:
1. **ANALYZE CONTENT, NOT JUST HEADERS**: Look at actual data values to understand what each column contains
2. **SPLIT COMBINED NAMES**: If you find "Full Name", "Contact", or combined name fields, map them to BOTH first_name AND last_name
3. **EXTRACT FROM TEXT**: If names are buried in descriptions or summaries, extract them
4. **BE CREATIVE**: Names might be in unexpected places like "Primary Contact", "Owner", "Representative"
5. **HANDLE FORMATS**: Parse "Last, First", "First Last", "Mr. John Smith", etc.
6. **FIND HIDDEN DATA**: Email domains can reveal company names, descriptions can contain contact info
7. **SMART INFERENCE**: Use context clues from multiple columns to make intelligent mappings

EXAMPLES OF SMART MAPPING:
- "Contact Person: John Smith" → first_name: "John", last_name: "Smith"
- "Owner" column with "Sarah Johnson" → first_name: "Sarah", last_name: "Johnson"  
- "Primary Contact" → Split into first_name + last_name
- "Representative" → Split into first_name + last_name
- "About Us: Founded by Mike Davis..." → first_name: "Mike", last_name: "Davis"
- Email "john@acme.com" → first_name: "john", company clue: "acme"

CRITICAL: If you find ANY column that contains human names (even if header doesn't say "name"), extract and split them into first_name and last_name.

OUTPUT (JSON only - no markdown):
{{
  "mapping": {{
    "input_header_1": "target_field",
    "input_header_2": "target_field"
  }},
  "split_fields": {{
    "combined_name_header": {{"first_name": "extracted_first", "last_name": "extracted_last"}}
  }},
  "unmapped": ["headers_that_have_no_useful_data"]
}}"""

        return prompt
    
    async def _call_gemini(self, prompt: str) -> str:
        """Make async call to Gemini API"""
        try:
            # Use asyncio to run the synchronous call in a thread
            loop = asyncio.get_event_loop()
            
            def _sync_call():
                response = self.model.generate_content(
                    prompt,
                    safety_settings={
                        HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
                        HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
                        HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
                        HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
                    }
                )
                # Handle different response formats for newer google-genai versions
                try:
                    # Try the simple text accessor first
                    return response.text
                except Exception:
                    # Fall back to the detailed accessor for complex responses
                    if hasattr(response, 'candidates') and response.candidates and len(response.candidates) > 0:
                        candidate = response.candidates[0]
                        if hasattr(candidate, 'content') and hasattr(candidate.content, 'parts') and len(candidate.content.parts) > 0:
                            return candidate.content.parts[0].text
                        else:
                            raise ValueError(f"Unexpected candidate structure: {candidate}")
                    else:
                        raise ValueError(f"No candidates in Gemini response: {response}")
            
            return await loop.run_in_executor(None, _sync_call)
            
        except Exception as e:
            logger.error(f"Gemini API call failed: {e}")
            raise
    
    def _parse_mapping_response(self, response: str, input_headers: List[str]) -> HeaderMapping:
        """Parse and validate Gemini response"""
        try:
            # Clean up response - remove markdown code blocks if present
            cleaned_response = response.strip()
            if cleaned_response.startswith('```json'):
                cleaned_response = cleaned_response[7:]  # Remove ```json
            if cleaned_response.startswith('```'):
                cleaned_response = cleaned_response[3:]   # Remove ```
            if cleaned_response.endswith('```'):
                cleaned_response = cleaned_response[:-3]  # Remove closing ```
            
            cleaned_response = cleaned_response.strip()
            
            # Try to parse JSON
            response_data = json.loads(cleaned_response)
            
            if not isinstance(response_data, dict):
                raise ValueError("Response is not a JSON object")
            
            mapping = response_data.get("mapping", {})
            split_fields = response_data.get("split_fields", {})
            unmapped = response_data.get("unmapped", [])
            
            # Validate mapping
            validated_mapping = {}
            validation_errors = []
            
            for input_header, target_header in mapping.items():
                if input_header not in input_headers:
                    validation_errors.append(f"Input header '{input_header}' not in original headers")
                    continue
                    
                if target_header not in TARGET_COLUMNS:
                    validation_errors.append(f"Target header '{target_header}' not in allowed targets")
                    continue
                    
                if target_header in validated_mapping.values():
                    validation_errors.append(f"Target header '{target_header}' mapped multiple times")
                    continue
                    
                validated_mapping[input_header] = target_header
            
            # Process split fields (intelligent name splitting)
            for input_header, split_info in split_fields.items():
                if input_header not in input_headers:
                    validation_errors.append(f"Split field header '{input_header}' not in original headers")
                    continue
                
                # Mark this field for intelligent splitting during processing
                validated_mapping[f"{input_header}__SPLIT__"] = "split_names"
                logger.info(f"Will intelligently split '{input_header}' into first_name and last_name")
            
            # Add unmapped headers for inputs not in mapping
            all_unmapped = list(set(unmapped + [h for h in input_headers if h not in validated_mapping]))
            
            if validation_errors:
                logger.warning(f"Mapping validation errors: {validation_errors}")
                # Continue with valid mappings only
            
            return HeaderMapping(
                mapping=validated_mapping,
                unmapped=all_unmapped
            )
            
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse Gemini response as JSON: {e}")
            logger.error(f"Raw response: '{response}' (length: {len(response)})")
            
            # Try to extract JSON from the response if it's wrapped in text
            import re
            json_match = re.search(r'\{.*\}', response, re.DOTALL)
            if json_match:
                try:
                    response_data = json.loads(json_match.group())
                    logger.info("Successfully extracted JSON from wrapped response")
                except json.JSONDecodeError:
                    pass
                else:
                    # Continue with the extracted JSON
                    pass
            
            if not response.strip():
                raise ValueError("Gemini returned empty response")
            else:
                raise ValueError(f"Invalid JSON response from Gemini. Response: '{response[:200]}...' Length: {len(response)}")
        except Exception as e:
            logger.error(f"Error parsing mapping response: {e}")
            raise
