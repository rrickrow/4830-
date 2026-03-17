from __future__ import annotations

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.platypus import Image as RLImage
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from river_insight.domain.models import AnalysisRequest, AnalysisResult
from river_insight.labels import APP_TITLE, STAGE_LABELS, provider_label, study_area_label


class ReportService:
    def __init__(self) -> None:
        try:
            pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
        except (KeyError, ValueError):
            pass

    def build_pdf(self, result: AnalysisResult, request: AnalysisRequest) -> Path:
        if result.output_dir is None:
            raise ValueError("AnalysisResult.output_dir 未设置，无法生成报告。")

        path = result.output_dir / "analysis_report.pdf"
        document = SimpleDocTemplate(str(path), pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm)

        styles = getSampleStyleSheet()
        font_name = "STSong-Light"
        title_style = ParagraphStyle(
            "TitleCN",
            parent=styles["Title"],
            fontName=font_name,
            fontSize=18,
            leading=22,
            spaceAfter=12,
        )
        body_style = ParagraphStyle(
            "BodyCN",
            parent=styles["BodyText"],
            fontName=font_name,
            fontSize=10.5,
            leading=16,
        )
        heading_style = ParagraphStyle(
            "HeadingCN",
            parent=styles["Heading2"],
            fontName=font_name,
            fontSize=13,
            leading=18,
            spaceBefore=8,
            spaceAfter=6,
        )

        summary_text = (
            f"研究区：{study_area_label(request.study_area)}；"
            f"分析年份：{request.start_year}-{request.end_year}；"
            f"步长：{request.year_step} 年；"
            f"数据源：{provider_label(request.provider)}；"
            f"运行编号：{result.run_id}。"
        )

        story = [
            Paragraph(APP_TITLE, title_style),
            Paragraph(summary_text, body_style),
            Spacer(1, 8),
            Paragraph("年度指标摘要", heading_style),
        ]

        annual = result.annual_metrics.fillna("")
        annual_table_data = [list(annual.columns)] + annual.round(4).astype(str).values.tolist()[:8]
        annual_table = Table(annual_table_data, repeatRows=1)
        annual_table.setStyle(
            TableStyle(
                [
                    ("FONTNAME", (0, 0), (-1, -1), font_name),
                    ("FONTSIZE", (0, 0), (-1, -1), 8),
                    ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                    ("GRID", (0, 0), (-1, -1), 0.3, colors.grey),
                ]
            )
        )
        story.append(annual_table)
        story.append(Spacer(1, 8))

        story.append(Paragraph("运行阶段", heading_style))
        stage_rows = [["阶段", "状态", "耗时(s)", "异常摘要"]]
        for record in result.manifest.stage_records:
            stage_rows.append(
                [
                    STAGE_LABELS.get(record.stage, record.stage),
                    record.status,
                    "" if record.duration_seconds is None else f"{record.duration_seconds:.2f}",
                    record.error_summary or "",
                ]
            )
        stage_table = Table(stage_rows, repeatRows=1)
        stage_table.setStyle(
            TableStyle(
                [
                    ("FONTNAME", (0, 0), (-1, -1), font_name),
                    ("FONTSIZE", (0, 0), (-1, -1), 8),
                    ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                    ("GRID", (0, 0), (-1, -1), 0.3, colors.grey),
                ]
            )
        )
        story.append(stage_table)
        story.append(Spacer(1, 8))

        story.append(Paragraph("核心图表", heading_style))
        for key in (
            "true_color_panel_png",
            "water_masks_panel_png",
            "centerline_overlay_png",
            "fvc_heatmap_png",
            "regression_png",
            "ndvi_quality_png",
        ):
            image_path = result.artifacts.get(key)
            if not image_path:
                continue
            story.append(RLImage(str(image_path), width=170 * mm, height=90 * mm))
            story.append(Spacer(1, 5))

        story.append(Paragraph("质量检查", heading_style))
        story.append(Paragraph(result.quality_report.get("summary", "无"), body_style))
        issues = result.quality_report.get("issues", [])
        if issues:
            for issue in issues[:8]:
                story.append(Paragraph(f"- {issue['message']}", body_style))

        story.append(Paragraph("回归结果", heading_style))
        regression = result.regression_summary
        story.append(
            Paragraph(
                (
                    f"状态：{regression.get('status')}；"
                    f"样本数：{regression.get('sample_count')}；"
                    f"R²：{regression.get('r_squared')}；"
                    f"调整后 R²：{regression.get('adjusted_r_squared')}"
                ),
                body_style,
            )
        )
        coefficients = regression.get("coefficients")
        if coefficients is not None and not coefficients.empty:
            coeff_frame = coefficients.round(4).astype(str)
            coeff_table = Table([list(coeff_frame.columns)] + coeff_frame.values.tolist(), repeatRows=1)
            coeff_table.setStyle(
                TableStyle(
                    [
                        ("FONTNAME", (0, 0), (-1, -1), font_name),
                        ("FONTSIZE", (0, 0), (-1, -1), 8),
                        ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                        ("GRID", (0, 0), (-1, -1), 0.3, colors.grey),
                    ]
                )
            )
            story.append(coeff_table)
            story.append(Spacer(1, 8))

        story.append(Paragraph("数据源摘要", heading_style))
        years = result.source_inventory.get("years", {})
        if years:
            for year, payload in list(years.items())[:6]:
                optical = payload.get("optical") or {}
                landcover = payload.get("landcover") or {}
                precipitation = payload.get("precipitation") or {}
                summary = (
                    f"{year}："
                    f"光学源={','.join(optical.get('collections', [])) or '无'}；"
                    f"土地覆盖={landcover.get('collection', '无')}({landcover.get('source_year', '-')})；"
                    f"降水={precipitation.get('version', '无')}"
                )
                story.append(Paragraph(summary, body_style))

        story.append(Paragraph("结论与告警", heading_style))
        warning_text = "；".join(result.warnings) if result.warnings else "本次运行未出现阻断性异常。"
        story.append(Paragraph(warning_text, body_style))

        story.append(Paragraph("产物清单", heading_style))
        for key, value in result.artifacts.items():
            if not isinstance(value, Path):
                continue
            story.append(Paragraph(f"{key}: {value.name}", body_style))

        document.build(story)
        return path
