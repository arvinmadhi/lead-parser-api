"""
Logging utilities for the Lead Parser API
"""
import logging
import sys
from typing import Any, Dict
from pythonjsonlogger import jsonlogger


class CorrelationIdFilter(logging.Filter):
    """Filter to add correlation ID to log records"""
    
    def filter(self, record):
        if not hasattr(record, 'correlation_id'):
            record.correlation_id = 'unknown'
        return True


class CustomJsonFormatter(jsonlogger.JsonFormatter):
    """Custom JSON formatter for structured logging"""
    
    def add_fields(self, log_record: Dict[str, Any], record: logging.LogRecord, message_dict: Dict[str, Any]):
        super().add_fields(log_record, record, message_dict)
        
        # Add standard fields
        log_record['timestamp'] = self.formatTime(record, self.datefmt)
        log_record['level'] = record.levelname
        log_record['logger'] = record.name
        log_record['module'] = record.module
        log_record['function'] = record.funcName
        log_record['line'] = record.lineno
        
        # Add correlation ID if available
        if hasattr(record, 'correlation_id'):
            log_record['correlation_id'] = record.correlation_id
        
        # Add any extra fields
        if hasattr(record, 'model_id'):
            log_record['model_id'] = record.model_id
        
        if hasattr(record, 'phase'):
            log_record['phase'] = record.phase
        
        if hasattr(record, 'timing_ms'):
            log_record['timing_ms'] = record.timing_ms
        
        if hasattr(record, 'row_count'):
            log_record['row_count'] = record.row_count


def setup_logging():
    """Setup structured JSON logging"""
    
    # Create custom formatter
    formatter = CustomJsonFormatter(
        fmt='%(asctime)s %(levelname)s %(name)s %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    # Setup root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    
    # Remove existing handlers
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
    
    # Create console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    
    # Add correlation ID filter
    console_handler.addFilter(CorrelationIdFilter())
    
    root_logger.addHandler(console_handler)
    
    # Set specific logger levels
    logging.getLogger('httpx').setLevel(logging.WARNING)
    logging.getLogger('google').setLevel(logging.WARNING)
    logging.getLogger('googleapiclient').setLevel(logging.WARNING)
    logging.getLogger('urllib3').setLevel(logging.WARNING)
    
    logging.info("Structured logging initialized")


class TimingLogger:
    """Helper class for timing operations"""
    
    def __init__(self, logger: logging.Logger, correlation_id: str):
        self.logger = logger
        self.correlation_id = correlation_id
        self.timings = {}
    
    def log_timing(self, phase: str, timing_ms: int, **extra_fields):
        """Log timing for a specific phase"""
        self.timings[phase] = timing_ms
        
        # Create log record with extra fields (no correlation_id since middleware sets it)
        extra = {
            'phase': phase,
            'timing_ms': timing_ms,
            **extra_fields
        }
        
        self.logger.info(f"Phase '{phase}' completed in {timing_ms}ms", extra=extra)
    
    def get_timings(self) -> Dict[str, int]:
        """Get all recorded timings"""
        return self.timings.copy()
