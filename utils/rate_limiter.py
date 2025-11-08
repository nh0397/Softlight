"""
Rate limiter for API calls to respect service limits
"""
import time
from collections import deque


class RateLimiter:
    """Simple rate limiter to track API calls and enforce limits"""
    
    def __init__(self, max_calls: int = 15, time_window: int = 60):
        """
        Initialize rate limiter
        
        Args:
            max_calls: Maximum number of calls allowed in the time window
            time_window: Time window in seconds (default: 60 for per-minute limit)
        """
        self.max_calls = max_calls
        self.time_window = time_window
        self.call_times = deque()
    
    def wait_if_needed(self):
        """
        Check if we need to wait before making another API call.
        Blocks until it's safe to proceed.
        """
        now = time.time()
        
        # Remove calls outside the time window
        while self.call_times and self.call_times[0] < now - self.time_window:
            self.call_times.popleft()
        
        # If we've hit the limit, wait until the oldest call expires
        if len(self.call_times) >= self.max_calls:
            wait_time = self.call_times[0] + self.time_window - now
            if wait_time > 0:
                print(f"⏳ Rate limit: waiting {wait_time:.1f}s before next API call...")
                time.sleep(wait_time + 0.5)  # Add 0.5s buffer
                # Clean up old calls after waiting
                now = time.time()
                while self.call_times and self.call_times[0] < now - self.time_window:
                    self.call_times.popleft()
        
        # Record this call
        self.call_times.append(time.time())
    
    def get_remaining_calls(self) -> int:
        """Get number of remaining calls available in current window"""
        now = time.time()
        # Remove calls outside the time window
        while self.call_times and self.call_times[0] < now - self.time_window:
            self.call_times.popleft()
        return max(0, self.max_calls - len(self.call_times))

