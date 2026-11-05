"""공식 평가 지표의 항목 상태와 run 집계 모델."""

from dataclasses import dataclass, field
from typing import Any, Literal, Optional, Sequence


MetricStatus = Literal["evaluated", "excluded", "error"]


@dataclass(frozen=True)
class MetricResult:
    value: Optional[float]
    status: MetricStatus
    reason: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.status == "evaluated" and self.value is None:
            raise ValueError("evaluated metric requires a value")
        if self.status != "evaluated" and self.value is not None:
            raise ValueError("excluded/error metric cannot have a value")

    def as_dict(self) -> dict[str, Any]:
        return {
            "value": self.value,
            "status": self.status,
            "reason": self.reason,
            "metadata": self.metadata,
        }


@dataclass(frozen=True)
class MetricAggregate:
    value: Optional[float]
    std: Optional[float]
    evaluated_count: int
    excluded_count: int
    error_count: int
    total_count: int

    @classmethod
    def from_results(cls, results: Sequence[MetricResult]) -> "MetricAggregate":
        values = [float(result.value) for result in results if result.status == "evaluated"]
        evaluated = len(values)
        excluded = sum(result.status == "excluded" for result in results)
        errors = sum(result.status == "error" for result in results)
        mean = sum(values) / evaluated if evaluated else None
        variance = (
            sum((value - mean) ** 2 for value in values) / evaluated
            if evaluated and mean is not None else None
        )
        return cls(
            value=mean,
            std=variance ** 0.5 if variance is not None else None,
            evaluated_count=evaluated,
            excluded_count=excluded,
            error_count=errors,
            total_count=evaluated + excluded + errors,
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "value": self.value,
            "std": self.std,
            "evaluated_count": self.evaluated_count,
            "excluded_count": self.excluded_count,
            "error_count": self.error_count,
            "total_count": self.total_count,
        }
