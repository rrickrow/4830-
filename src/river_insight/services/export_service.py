from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import geopandas as gpd
import matplotlib.figure
import matplotlib.pyplot as plt
import pandas as pd

from river_insight import config


class ExportService:
    def __init__(
        self,
        app_config: config.AppConfig | None = None,
        output_root: Path | None = None,
    ) -> None:
        self.app_config = app_config or config.load_app_config()
        self.output_root = output_root or self.app_config.output_root

    def generate_run_id(self, provider_name: str) -> str:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
        return f"{timestamp}_{provider_name}"

    def create_run_directory(self, run_id: str) -> Path:
        run_dir = self.output_root / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        return run_dir

    def write_dataframe(self, frame: pd.DataFrame, output_dir: Path, filename: str) -> Path:
        path = output_dir / filename
        frame.to_csv(path, index=False, encoding="utf-8-sig")
        return path

    def write_geojson(self, gdf: gpd.GeoDataFrame, output_dir: Path, filename: str) -> Path:
        path = output_dir / filename
        path.write_text(gdf.to_json(drop_id=True, ensure_ascii=False), encoding="utf-8")
        return path

    def write_text(self, content: str, output_dir: Path, filename: str) -> Path:
        path = output_dir / filename
        path.write_text(content, encoding="utf-8")
        return path

    def write_json(self, payload: dict[str, Any], output_dir: Path, filename: str) -> Path:
        path = output_dir / filename
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def save_figure(
        self,
        figure: matplotlib.figure.Figure,
        output_dir: Path,
        filename: str,
    ) -> Path:
        path = output_dir / filename
        figure.savefig(path, dpi=180, bbox_inches="tight")
        plt.close(figure)
        return path

    def list_runs(self, limit: int = 20) -> list[dict[str, Any]]:
        if not self.output_root.exists():
            return []
        records: list[dict[str, Any]] = []
        for run_dir in sorted(self.output_root.iterdir(), reverse=True):
            if not run_dir.is_dir():
                continue
            manifest_path = run_dir / "manifest.json"
            if not manifest_path.exists():
                continue
            try:
                payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            payload["output_dir"] = str(run_dir.resolve())
            records.append(payload)
            if len(records) >= limit:
                break
        return records

    def read_json(self, path: Path) -> dict[str, Any]:
        return json.loads(path.read_text(encoding="utf-8"))
