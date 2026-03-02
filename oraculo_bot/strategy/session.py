import time
from typing import List, Tuple

def is_session_allowed(allowed_ranges: List[Tuple[int, int]], current_time=None) -> bool:
    if current_time is None:
        current_time = time.gmtime()
    hour = current_time.tm_hour
    for start, end in allowed_ranges:
        if start <= hour < end:
            return True
    return False