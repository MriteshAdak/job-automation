"""Synthetic limits fixtures for SF-04 capacity testing."""

SYNTHETIC_LIMITS_HEALTHY = {
    "DailyApiRequests": {"Max": 15000, "Remaining": 14000},
    "DataStorageMB": {"Max": 100, "Remaining": 80},
    "FileStorageMB": {"Max": 100, "Remaining": 80},
}

SYNTHETIC_LIMITS_TIGHT = {
    "DailyApiRequests": {"Max": 100, "Remaining": 25},  # Used: 75
    "DataStorageMB": {"Max": 10, "Remaining": 0},       # Exhausted / Blocked
    "FileStorageMB": {"Max": 20, "Remaining": 2},       # Near reserve -> Warning
}

SYNTHETIC_LIMITS_EXHAUSTED = {
    "DailyApiRequests": {"Max": 1000, "Remaining": 0},
    "DataStorageMB": {"Max": 10, "Remaining": 0},
    "FileStorageMB": {"Max": 20, "Remaining": 0},
}

SYNTHETIC_LIMITS_ZERO_MAX = {
    "DailyApiRequests": {"Max": 0, "Remaining": 0},
    "DataStorageMB": {"Max": 0, "Remaining": 0},
}

SYNTHETIC_LIMITS_INCONSISTENT = {
    "DailyApiRequests": {"Max": 100, "Remaining": 150},  # Remaining > Max
    "DataStorageMB": {"Max": 10, "Remaining": -1},       # Negative remaining
}
