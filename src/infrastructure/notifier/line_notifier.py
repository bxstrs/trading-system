"""LINE Notify integration for critical alerts and manual review notifications."""
import os
import time
import requests
from typing import Optional

from src.infrastructure.logger.logger import log


class LineNotifier:
    API_URL = "https://notify-api.line.me/api/notify"

    def __init__(self, token: Optional[str] = None):
        self.token = token or os.getenv("LINE_NOTIFY_TOKEN")
        self.enabled = bool(self.token)
        if self.enabled:
            log("LINE Notifications enabled", level="DEBUG")
        else:
            log("LINE Notify token not set; notifications disabled", level="DEBUG")

    def notify(self, message: str, max_retries: int = 3) -> bool:

        if not self.enabled:
            return False
        headers = {
            "Authorization": f"Bearer {self.token}",
        }
        payload = {
            "message": message,
        }

        for attempt in range(1, max_retries + 1):
            try:
                response = requests.post(
                    self.API_URL, headers=headers, data=payload, timeout=5
                )
                if response.status_code == 200:
                    log(f"LINE Notify success: {message}", level="DEBUG")
                    return True
                log(
                    f"LINE Notify HTTP {response.status_code}: {response.text}",
                    level="WARNING"
                )
                
            except requests.Timeout:
                if attempt < max_retries:
                    time.sleep(0.5 * (2 ** (attempt - 1)))
                    continue
                log(f"LINE notify timed out after {max_retries} attempts", level="ERROR")

            except Exception as exc:
                log(f"LINE Notify request failed: {exc}", level="ERROR")
                return False
            
            log(
                f"LINE Notify failed after {max_retries} attempts",
                level="ERROR"
            )
        return False
