__all__ = ["AnalysisRequest", "AnalysisResult", "AnalysisService"]


def __getattr__(name: str):
    if name == "AnalysisRequest":
        from river_insight.domain.models import AnalysisRequest

        return AnalysisRequest
    if name == "AnalysisResult":
        from river_insight.domain.models import AnalysisResult

        return AnalysisResult
    if name == "AnalysisService":
        from river_insight.services.analysis_service import AnalysisService

        return AnalysisService
    raise AttributeError(f"module 'river_insight' has no attribute {name!r}")
