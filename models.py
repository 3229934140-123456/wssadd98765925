from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, List, Optional

if TYPE_CHECKING:
    from config import ScreenRules


class ReeferStatus(Enum):
    ON = "ON"
    OFF = "OFF"
    FAULT = "FAULT"


class AnomalyLabel(Enum):
    TIRE_PRESSURE_DRAG_COOLING = "疑似胎压拖累制冷"
    PURE_TEMP_FLUCTUATION = "单纯温度波动"
    SENSOR_MALFUNCTION = "传感器可能失准"


@dataclass
class LogRecord:
    timestamp: datetime
    plate: str
    route: str
    wheel_positions: dict
    compartment_temp: float
    reefer_status: ReeferStatus

    def is_tire_pressure_abnormal(self, low=4.5, high=8.0) -> List[str]:
        abnormal = []
        for pos, pressure in self.wheel_positions.items():
            if pressure is None:
                abnormal.append(pos)
            elif pressure < low or pressure > high:
                abnormal.append(pos)
        return abnormal


@dataclass
class Trip:
    plate: str
    route: str
    start_time: datetime
    end_time: datetime
    records: List[LogRecord] = field(default_factory=list)

    @property
    def duration_minutes(self) -> float:
        if not self.records:
            return 0.0
        delta = self.end_time - self.start_time
        return delta.total_seconds() / 60.0

    @property
    def date_str(self) -> str:
        return self.start_time.strftime("%Y-%m-%d")

    def __str__(self):
        return (
            f"[{self.plate}] {self.route} | "
            f"{self.start_time.strftime('%Y-%m-%d %H:%M')}~"
            f"{self.end_time.strftime('%H:%M')} "
            f"({self.duration_minutes:.0f}min)"
        )


@dataclass
class AnomalySegment:
    start_time: datetime
    duration_minutes: float
    abnormal_wheels: List[str]
    temp_change: float
    reefer_cycles: int
    label: AnomalyLabel
    plate: str
    route: str
    detail: str = ""

    def __str__(self):
        return (
            f"[{self.plate}] {self.route} | "
            f"{self.start_time.strftime('%Y-%m-%d %H:%M')} | "
            f"持续{self.duration_minutes:.0f}min | "
            f"异常轮位:{','.join(self.abnormal_wheels) if self.abnormal_wheels else '无'} | "
            f"厢温变化:{self.temp_change:+.1f}°C | "
            f"冷机启停{self.reefer_cycles}次 | "
            f"【{self.label.value}】"
        )


@dataclass
class ReviewSummary:
    plate: str
    route: str
    date_range: str
    high_risk_periods: List[str]
    missing_driver_records: List[str]
    recommended_wheel_checks: List[str]
    anomaly_count: int
    raw_segments: List[AnomalySegment] = field(default_factory=list)

    def to_text_report(self, rules: Optional["ScreenRules"] = None, route: Optional[str] = None) -> str:
        lines = []
        lines.append("=" * 60)
        lines.append("冷链运输监控复盘摘要")
        lines.append("=" * 60)
        lines.append(f"车牌: {self.plate}")
        lines.append(f"线路: {self.route}")
        lines.append(f"日期范围: {self.date_range}")
        lines.append(f"异常片段总数: {self.anomaly_count}")
        lines.append("")

        if rules:
            lines.append("-" * 60)
            lines.append("本次采用筛查规则")
            lines.append("-" * 60)
            lines.append(rules.to_markdown(route))
            lines.append("")

        lines.append("-" * 60)
        lines.append("高风险时段")
        lines.append("-" * 60)
        if self.high_risk_periods:
            for p in self.high_risk_periods:
                lines.append(f"  - {p}")
        else:
            lines.append("  无")

        lines.append("")
        lines.append("-" * 60)
        lines.append("司机处置记录缺失点")
        lines.append("-" * 60)
        if self.missing_driver_records:
            for m in self.missing_driver_records:
                lines.append(f"  - {m}")
        else:
            lines.append("  无")

        lines.append("")
        lines.append("-" * 60)
        lines.append("建议复查轮位")
        lines.append("-" * 60)
        if self.recommended_wheel_checks:
            for w in self.recommended_wheel_checks:
                lines.append(f"  - {w}")
        else:
            lines.append("  无")

        lines.append("")
        lines.append("-" * 60)
        lines.append("异常片段明细")
        lines.append("-" * 60)
        for seg in self.raw_segments:
            lines.append(f"  {seg}")
            if seg.detail:
                lines.append(f"    -> {seg.detail}")

        lines.append("")
        lines.append("=" * 60)
        lines.append("报告生成时间: " + datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        lines.append("=" * 60)
        return "\n".join(lines)
