import json
from datetime import datetime, timezone
from pathlib import Path

from app.core.config import settings


def write_raw_json(dataset: str, payload) -> str:
    now = datetime.now(timezone.utc)

    folder = (
        Path(settings.raw_data_dir)
        / dataset
        / f"dt={now:%Y-%m-%d}"
    )

    folder.mkdir(parents=True, exist_ok=True)

    path = folder / f"{now:%H%M%S_%f}.json"

    path.write_text(
        json.dumps(payload, default=str, indent=2),
        encoding="utf-8",
    )

    return str(path)
