"""
Data processing service for normalizing and cleaning lead data
"""
import re
import logging
import pandas as pd
from typing import Dict, List, Tuple, Any
from urllib.parse import urlparse, urlunparse
import phonenumbers
from email_validator import validate_email, EmailNotValidError

from app.models import TARGET_COLUMNS, DropRecord, ProcessingStats, ParseOptions

logger = logging.getLogger(__name__)


class DataProcessor:
    """Service for processing and normalizing lead data"""
    
    def __init__(self, options: ParseOptions):
        self.options = options
        self.drops: List[DropRecord] = []
    
    def process_dataframe(self, df: pd.DataFrame, mapping: Dict[str, str]) -> Tuple[pd.DataFrame, List[DropRecord], ProcessingStats]:
        """
        Process the dataframe: map headers, normalize data, remove empty rows, deduplicate
        
        Args:
            df: Input dataframe
            mapping: Header mapping from input to target columns
            
        Returns:
            Tuple of (processed_dataframe, drop_records, stats)
        """
        logger.info(f"Processing dataframe with {len(df)} rows")
        
        # Reset drops for this processing run
        self.drops = []
        
        # Step 1: Apply header mapping and create target dataframe
        processed_df = self._apply_header_mapping(df, mapping)
        
        # Step 2: Normalize all fields
        processed_df = self._normalize_fields(processed_df)
        
        # Step 3: Remove empty rows
        processed_df = self._remove_empty_rows(processed_df)
        
        # Step 4: Deduplicate if requested
        if self.options.one_contact_per_company:
            processed_df = self._deduplicate_contacts(processed_df)
        
        # Step 5: Add source label if provided
        if self.options.source_label:
            processed_df = self._add_source_labels(processed_df)
        
        # Calculate stats
        stats = self._calculate_stats(processed_df, len(df))
        
        logger.info(f"Processing complete: {len(processed_df)} rows output, {len(self.drops)} rows dropped")
        
        return processed_df, self.drops, stats
    
    def _apply_header_mapping(self, df: pd.DataFrame, mapping: Dict[str, str]) -> pd.DataFrame:
        """Apply header mapping and create target structure"""
        
        # Create new dataframe with target columns
        result_df = pd.DataFrame(columns=TARGET_COLUMNS)
        
        # Map data from input columns to target columns
        for input_col, target_col in mapping.items():
            if input_col in df.columns:
                result_df[target_col] = df[input_col]
            elif input_col.endswith("__SPLIT__") and target_col == "split_names":
                # Handle intelligent name splitting
                original_col = input_col.replace("__SPLIT__", "")
                if original_col in df.columns:
                    logger.info(f"Intelligently splitting names from column: {original_col}")
                    first_names, last_names = self._split_names_intelligently(df[original_col])
                    result_df["first_name"] = first_names
                    result_df["last_name"] = last_names
            else:
                logger.warning(f"Input column '{input_col}' not found in dataframe")
        
        # Fill missing columns with empty strings
        for col in TARGET_COLUMNS:
            if col not in result_df.columns:
                result_df[col] = ""
        
        # Ensure column order
        result_df = result_df[TARGET_COLUMNS]
        
        return result_df
    
    def _normalize_fields(self, df: pd.DataFrame) -> pd.DataFrame:
        """Normalize all fields according to the specifications"""
        
        df = df.copy()
        
        # Normalize names
        df['first_name'] = df['first_name'].apply(self._normalize_name)
        df['last_name'] = df['last_name'].apply(self._normalize_name)
        
        # Handle full name splitting if needed
        df = self._split_full_names(df)
        
        # Normalize company
        df['company_name'] = df['company_name'].apply(self._normalize_company)
        
        # Normalize email
        df['email'] = df['email'].apply(self._normalize_email)
        
        # Normalize phone
        df['phone_number'] = df['phone_number'].apply(self._normalize_phone)
        
        # Normalize job title
        df['job_title'] = df['job_title'].apply(self._normalize_job_title)
        
        # Normalize LinkedIn URL
        df['linkedin_url'] = df['linkedin_url'].apply(self._normalize_linkedin_url)
        
        # Normalize website
        df['website'] = df['website'].apply(self._normalize_website)
        
        # Normalize company summary
        df['company_summary'] = df['company_summary'].apply(self._normalize_summary)
        
        # Initialize sources if empty
        df['sources'] = df['sources'].apply(lambda x: str(x) if pd.notna(x) and str(x).strip() else "")
        
        return df
    
    def _normalize_name(self, name: Any) -> str:
        """Normalize a name field"""
        if pd.isna(name) or not str(name).strip():
            return ""
        
        name_str = str(name).strip()
        # Title case and clean up
        normalized = ' '.join(word.capitalize() for word in name_str.split())
        return normalized
    
    def _split_full_names(self, df: pd.DataFrame) -> pd.DataFrame:
        """Split full names if first_name is empty but last_name contains full name"""
        
        df = df.copy()
        
        for idx, row in df.iterrows():
            first_name = str(row['first_name']).strip()
            last_name = str(row['last_name']).strip()
            
            # If first_name is empty but last_name has multiple words, split
            if not first_name and last_name and ' ' in last_name:
                parts = last_name.split()
                if len(parts) >= 2:
                    df.at[idx, 'first_name'] = parts[0]
                    df.at[idx, 'last_name'] = ' '.join(parts[1:])
        
        return df
    
    def _normalize_company(self, company: Any) -> str:
        """Normalize company name"""
        if pd.isna(company) or not str(company).strip():
            return ""
        
        company_str = str(company).strip()
        # Preserve suffixes and capitalization for companies
        return company_str
    
    def _normalize_email(self, email: Any) -> str:
        """Normalize and validate email"""
        if pd.isna(email) or not str(email).strip():
            return ""
        
        email_str = str(email).strip().lower()
        
        try:
            # Basic validation using email-validator
            validated = validate_email(email_str)
            return validated.email
        except EmailNotValidError:
            # Use regex as fallback for RFC5322-like validation
            rfc5322_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
            if re.match(rfc5322_pattern, email_str):
                return email_str
            else:
                return ""
    
    def _normalize_phone(self, phone: Any) -> str:
        """Normalize phone number"""
        if pd.isna(phone) or not str(phone).strip():
            return ""
        
        phone_str = str(phone).strip()
        
        # Extract only numeric characters
        numeric_only = re.sub(r'[^\d+]', '', phone_str)
        
        if not numeric_only:
            return ""
        
        # Try to parse with phonenumbers library
        try:
            parsed = phonenumbers.parse(numeric_only, None)
            if phonenumbers.is_valid_number(parsed):
                return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
        except Exception:
            pass
        
        # Fallback: ensure leading + for international format
        if numeric_only and not numeric_only.startswith('+'):
            if len(numeric_only) == 10:  # US number
                numeric_only = '+1' + numeric_only
            elif len(numeric_only) == 11 and numeric_only.startswith('1'):  # US with country code
                numeric_only = '+' + numeric_only
            else:
                numeric_only = '+' + numeric_only
        
        return numeric_only if numeric_only else ""
    
    def _normalize_job_title(self, title: Any) -> str:
        """Normalize job title"""
        if pd.isna(title) or not str(title).strip():
            return ""
        
        title_str = str(title).strip()
        # Collapse whitespace
        normalized = ' '.join(title_str.split())
        return normalized
    
    def _normalize_linkedin_url(self, url: Any) -> str:
        """Normalize LinkedIn URL"""
        if pd.isna(url) or not str(url).strip():
            return ""
        
        url_str = str(url).strip()
        
        # Check if it's a LinkedIn URL
        if 'linkedin.com' not in url_str.lower():
            return ""
        
        try:
            # Parse the URL
            parsed = urlparse(url_str)
            
            # Ensure it's linkedin.com
            if 'linkedin.com' not in parsed.netloc.lower():
                return ""
            
            # Standardize scheme
            if not parsed.scheme:
                parsed = parsed._replace(scheme='https')
            
            # Remove query parameters
            parsed = parsed._replace(query='', fragment='')
            
            return urlunparse(parsed)
            
        except Exception:
            return ""
    
    def _normalize_website(self, url: Any) -> str:
        """Normalize website URL"""
        if pd.isna(url) or not str(url).strip():
            return ""
        
        url_str = str(url).strip()
        
        try:
            # Parse the URL
            parsed = urlparse(url_str)
            
            # Add scheme if missing
            if not parsed.scheme:
                url_str = 'https://' + url_str
                parsed = urlparse(url_str)
            
            # Remove tracking parameters (common ones)
            if parsed.query:
                tracking_params = ['utm_source', 'utm_medium', 'utm_campaign', 'utm_content', 'utm_term', 'gclid', 'fbclid']
                query_params = []
                for param in parsed.query.split('&'):
                    if '=' in param:
                        key = param.split('=')[0]
                        if key not in tracking_params:
                            query_params.append(param)
                
                new_query = '&'.join(query_params)
                parsed = parsed._replace(query=new_query)
            
            # Remove fragment
            parsed = parsed._replace(fragment='')
            
            return urlunparse(parsed)
            
        except Exception:
            return url_str
    
    def _normalize_summary(self, summary: Any) -> str:
        """Normalize company summary"""
        if pd.isna(summary) or not str(summary).strip():
            return ""
        
        summary_str = str(summary).strip()
        
        # Truncate to 2000 characters as specified
        if len(summary_str) > 2000:
            summary_str = summary_str[:2000]
        
        return summary_str
    
    def _remove_empty_rows(self, df: pd.DataFrame) -> pd.DataFrame:
        """Remove rows where all target fields are empty"""
        
        initial_count = len(df)
        
        # Check each row
        rows_to_keep = []
        for idx, row in df.iterrows():
            has_data = any(str(row[col]).strip() for col in TARGET_COLUMNS)
            if has_data:
                rows_to_keep.append(idx)
            else:
                self.drops.append(DropRecord(
                    row_index=idx,
                    reason="empty_row",
                    details="All target fields are empty"
                ))
        
        result_df = df.loc[rows_to_keep].reset_index(drop=True)
        
        dropped_count = initial_count - len(result_df)
        if dropped_count > 0:
            logger.info(f"Removed {dropped_count} empty rows")
        
        return result_df
    
    def _deduplicate_contacts(self, df: pd.DataFrame) -> pd.DataFrame:
        """Keep only one contact per company using priority rules"""
        
        if df.empty:
            return df
        
        # Group by company_name (case-insensitive, stripped)
        df['_company_normalized'] = df['company_name'].str.strip().str.lower()
        
        # Remove rows without company names
        df_with_company = df[df['_company_normalized'] != ''].copy()
        df_without_company = df[df['_company_normalized'] == ''].copy()
        
        if df_with_company.empty:
            return df_without_company.drop('_company_normalized', axis=1)
        
        # Priority scoring function
        def calculate_priority_score(row):
            score = 0
            
            # Verified email (contains @ and domain)
            if '@' in str(row['email']) and '.' in str(row['email']):
                score += 100
            
            # LinkedIn URL
            if str(row['linkedin_url']).strip():
                score += 50
            
            # Senior title keywords
            title = str(row['job_title']).lower()
            senior_keywords = ['ceo', 'cto', 'cfo', 'president', 'director', 'vp', 'vice president', 'head', 'chief', 'founder']
            if any(keyword in title for keyword in senior_keywords):
                score += 30
            
            # Completeness (number of non-empty fields)
            non_empty_fields = sum(1 for col in TARGET_COLUMNS if str(row[col]).strip())
            score += non_empty_fields
            
            return score
        
        # Calculate scores
        df_with_company['_priority_score'] = df_with_company.apply(calculate_priority_score, axis=1)
        
        # Keep highest priority contact per company
        kept_contacts = df_with_company.loc[df_with_company.groupby('_company_normalized')['_priority_score'].idxmax()]
        
        # Track duplicates
        all_company_rows = df_with_company.groupby('_company_normalized').apply(lambda x: x.index.tolist()).to_dict()
        for company, row_indices in all_company_rows.items():
            if len(row_indices) > 1:
                kept_idx = kept_contacts[kept_contacts['_company_normalized'] == company].index[0]
                for idx in row_indices:
                    if idx != kept_idx:
                        original_idx = df_with_company.loc[idx].name
                        self.drops.append(DropRecord(
                            row_index=original_idx,
                            reason="duplicate_contact",
                            details=f"Duplicate contact for company: {company}"
                        ))
        
        # Combine results
        result_df = pd.concat([kept_contacts, df_without_company], ignore_index=True)
        result_df = result_df.drop(['_company_normalized', '_priority_score'], axis=1, errors='ignore')
        
        dedup_removed = len(df) - len(result_df)
        if dedup_removed > 0:
            logger.info(f"Removed {dedup_removed} duplicate contacts")
        
        return result_df
    
    def _add_source_labels(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add source label to the sources field"""
        
        df = df.copy()
        
        for idx, row in df.iterrows():
            existing_sources = str(row['sources']).strip()
            if existing_sources:
                new_sources = f"{existing_sources}, {self.options.source_label}"
            else:
                new_sources = self.options.source_label
            
            df.at[idx, 'sources'] = new_sources
        
        return df
    
    def _split_names_intelligently(self, name_series: pd.Series) -> Tuple[pd.Series, pd.Series]:
        """Intelligently split combined names into first and last names"""
        first_names = []
        last_names = []
        
        for name in name_series:
            if pd.isna(name) or not str(name).strip():
                first_names.append("")
                last_names.append("")
                continue
                
            name_str = str(name).strip()
            
            # Handle various name formats
            if "," in name_str:
                # "Last, First" format
                parts = name_str.split(",", 1)
                last_name = parts[0].strip()
                first_name = parts[1].strip() if len(parts) > 1 else ""
            else:
                # "First Last" or "First Middle Last" format
                parts = name_str.split()
                if len(parts) == 0:
                    first_name, last_name = "", ""
                elif len(parts) == 1:
                    first_name, last_name = parts[0], ""
                elif len(parts) == 2:
                    first_name, last_name = parts[0], parts[1]
                else:
                    # More than 2 parts - take first as first name, last as last name
                    first_name, last_name = parts[0], parts[-1]
                    
            # Clean up titles and prefixes
            first_name = self._clean_name_part(first_name)
            last_name = self._clean_name_part(last_name)
                    
            first_names.append(first_name)
            last_names.append(last_name)
        
        return pd.Series(first_names), pd.Series(last_names)
    
    def _clean_name_part(self, name_part: str) -> str:
        """Clean individual name parts by removing titles and extra characters"""
        if not name_part:
            return ""
            
        # Remove common titles and prefixes
        titles = ['mr.', 'mrs.', 'ms.', 'dr.', 'prof.', 'sir', 'madam']
        name_lower = name_part.lower().strip()
        
        for title in titles:
            if name_lower.startswith(title):
                name_part = name_part[len(title):].strip()
                break
        
        # Remove extra punctuation
        name_part = name_part.strip(".,;:()")
        
        return name_part.strip()
    
    def _calculate_stats(self, df: pd.DataFrame, original_count: int) -> ProcessingStats:
        """Calculate processing statistics"""
        
        if df.empty:
            return ProcessingStats(
                valid_email_ratio=0.0,
                linkedin_ratio=0.0,
                phone_ratio=0.0,
                company_ratio=0.0,
                total_rows=original_count,
                output_rows=0,
                dropped_rows=original_count
            )
        
        total_output = len(df)
        
        # Calculate ratios
        valid_emails = sum(1 for email in df['email'] if '@' in str(email) and str(email).strip())
        linkedin_profiles = sum(1 for url in df['linkedin_url'] if str(url).strip())
        phones = sum(1 for phone in df['phone_number'] if str(phone).strip())
        companies = sum(1 for company in df['company_name'] if str(company).strip())
        
        return ProcessingStats(
            valid_email_ratio=valid_emails / total_output if total_output > 0 else 0,
            linkedin_ratio=linkedin_profiles / total_output if total_output > 0 else 0,
            phone_ratio=phones / total_output if total_output > 0 else 0,
            company_ratio=companies / total_output if total_output > 0 else 0,
            total_rows=original_count,
            output_rows=total_output,
            dropped_rows=len(self.drops)
        )
