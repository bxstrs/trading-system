'''src/utils/logger.py'''
import time
import inspect
import os

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

LEVEL_PRIORITY = {
    "DEBUG": 10,
    "INFO": 20,
    "SIGNAL": 25,
    "WARNING": 30,
    "ERROR": 40,
    "CRITICAL": 50,
}

DEFAULT_LEVEL = "INFO"

# -----------------------------------------------------------------------------
# Safe logger
# -----------------------------------------------------------------------------

def log(msg: str, level: str = DEFAULT_LEVEL, source: str | None = None) -> None:

    try:
        # Normalize level
        level = str(level).upper()

        # Fallback for invalid level
        if level not in LEVEL_PRIORITY:
            level = DEFAULT_LEVEL

        current_log_level = LOG_LEVEL

        # Fallback for invalid env value
        if current_log_level not in LEVEL_PRIORITY:
            current_log_level = DEFAULT_LEVEL

        # Filter by log level
        if LEVEL_PRIORITY[level] < LEVEL_PRIORITY[current_log_level]:
            return

        # Auto source detection
        if source is None:
            try:
                frame = inspect.stack()[1]

                file_path = frame.filename
                file_name = os.path.basename(file_path)
                func_name = frame.function
                line_no = frame.lineno

                source = f"{file_name}:{func_name}:{line_no}"

            except Exception:
                source = "unknown"

        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")

        print(
            f"[{timestamp}] [{level}] [{source}] {msg}",
            flush=True
        )

    except Exception as e:
        # FINAL safety net
        # Logger must NEVER crash trading engine
        try:
            print(
                f"[LOGGER FAILURE] {e} | original_msg={msg}",
                flush=True
            )
        except Exception:
            pass