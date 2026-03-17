from __future__ import annotations

import argparse
import json

from river_insight import config
from river_insight.services.analysis_service import AnalysisService


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m river_insight.cli")
    subparsers = parser.add_subparsers(dest="command", required=True)

    doctor = subparsers.add_parser("doctor", help="检查配置、缓存目录和指定数据源健康状态")
    doctor.add_argument("--provider", default="public_stac", choices=list(config.ALLOWED_PROVIDERS))
    doctor.add_argument("--study-area", default="songhua", choices=list(config.ALLOWED_STUDY_AREAS))

    run = subparsers.add_parser("run", help="执行一次分析任务")
    run.add_argument("--study-area", default="songhua", choices=list(config.ALLOWED_STUDY_AREAS))
    run.add_argument("--start-year", type=int, default=config.DEFAULT_START_YEAR)
    run.add_argument("--end-year", type=int, default=config.DEFAULT_END_YEAR)
    run.add_argument("--year-step", type=int, default=config.DEFAULT_YEAR_STEP)
    run.add_argument("--provider", default=config.DEFAULT_PROVIDER, choices=list(config.ALLOWED_PROVIDERS))
    run.add_argument("--include-report", action="store_true")
    run.add_argument("--buffer-distances", default="300,600,1000")
    run.add_argument("--season-months", default="5,9")
    run.add_argument("--composite-strategy", default="median", choices=list(config.ALLOWED_COMPOSITE_STRATEGIES))
    run.add_argument("--disable-cache", action="store_true")
    run.add_argument("--allow-demo-fallback", action="store_true")

    list_runs = subparsers.add_parser("list-runs", help="列出历史运行清单")
    list_runs.add_argument("--limit", type=int, default=20)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    service = AnalysisService()

    if args.command == "doctor":
        payload = service.doctor(provider_name=args.provider, study_area=args.study_area)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0 if payload["status"] == "ok" else 1

    if args.command == "run":
        request = service.build_default_request()
        request.study_area = args.study_area
        request.start_year = args.start_year
        request.end_year = args.end_year
        request.year_step = args.year_step
        request.provider = args.provider
        request.include_report = bool(args.include_report)
        request.buffer_distances_m = tuple(int(item.strip()) for item in args.buffer_distances.split(","))
        request.season_months = tuple(int(item.strip()) for item in args.season_months.split(","))  # type: ignore[assignment]
        request.composite_strategy = args.composite_strategy
        request.use_cache = not args.disable_cache
        request.allow_demo_fallback = bool(args.allow_demo_fallback)
        result = service.run(request)
        print(
            json.dumps(
                {
                    "run_id": result.run_id,
                    "output_dir": str(result.output_dir.resolve()) if result.output_dir else None,
                    "status": result.manifest.status,
                    "warnings": result.warnings,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    if args.command == "list-runs":
        print(json.dumps(service.list_runs(limit=args.limit), ensure_ascii=False, indent=2))
        return 0

    parser.error(f"未知命令: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
