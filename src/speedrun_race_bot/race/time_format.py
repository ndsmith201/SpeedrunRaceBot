"""Conversions for the race timer's display format."""


def finish_time_to_milliseconds(value: str) -> int:
    """Convert an HH:MM:SS.mmm finish time to integer milliseconds."""
    hours, minutes, remainder = value.split(":")
    seconds, milliseconds = remainder.split(".")
    return int(hours) * 3_600_000 + int(minutes) * 60_000 + int(seconds) * 1_000 + int(milliseconds)
