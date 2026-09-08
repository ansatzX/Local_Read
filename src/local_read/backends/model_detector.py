"""Model readiness delegated to the managed MinerU configuration and inventory."""

from ..models import model_status


class ModelDetector:
    @property
    def mineru_available(self) -> bool:
        return model_status()["models_ready"]

    @property
    def mineru_warning(self) -> str | None:
        status = model_status()
        if status["models_ready"]:
            return None
        reasons = "; ".join(status["missing"][:5])
        return f"Local MinerU is not ready: {reasons}. Run 'local-read models prepare' online first. Using Simple when possible."


def get_model_detector() -> ModelDetector:
    return ModelDetector()
