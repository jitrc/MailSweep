"""Human-readable size formatting."""
from __future__ import annotations


def human_size(num_bytes: int | float, suffix: str = "B") -> str:
    """Convert bytes to a human-readable string like '2.3 MB'."""
    for unit in ("", "K", "M", "G", "T", "P", "E", "Z"):
        if abs(num_bytes) < 1024.0:
            if unit == "":
                return f"{int(num_bytes)} {suffix}"
            return f"{num_bytes:.1f} {unit}{suffix}"
        num_bytes /= 1024.0
    return f"{num_bytes:.1f} Y{suffix}"
