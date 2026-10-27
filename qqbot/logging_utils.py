import logging
import re


class RedactingFormatter(logging.Formatter):
    def __init__(self):
        super().__init__("%(asctime)s %(levelname)s %(name)s: %(message)s")
        self.secrets: set[str] = set()

    def add_secret(self, value: str) -> None:
        if value:
            self.secrets.add(value)

    def format(self, record: logging.LogRecord) -> str:
        text = super().format(record)
        for value in sorted(self.secrets, key=len, reverse=True):
            text = text.replace(value, "<redacted>")
        return re.sub(
            r"(?i)([?&](?:access_token|token|password|api_key)=)[^&\s]+",
            r"\1<redacted>",
            text,
        )


def configure_logging(level: str, *secrets: str) -> RedactingFormatter:
    formatter = RedactingFormatter()
    for value in secrets:
        formatter.add_secret(value)
    handler = logging.StreamHandler()
    handler.setFormatter(formatter)
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
    logging.getLogger("aiohttp.access").setLevel(logging.WARNING)
    return formatter
