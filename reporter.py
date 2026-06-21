import os
from collections import Counter
from datetime import datetime
from typing import List, Optional

from models import AnomalyLabel, AnomalySegment, ReviewSummary, Trip


def build_review_summary(
    plate: Optional[str],
    route: Optional[str],
    trips: List[Trip],
    segments: List[AnomalySegment],
) -> ReviewSummary:
    filtered_segments = segments
    if plate:
        filtered_segments = [s for s in filtered_segments if s.plate == plate]
    if route:
        filtered_segments = [s for s in filtered_segments if s.route == route]

    plate_val = plate or (filtered_segments[0].plate if filtered_segments else "全部")
    route_val = route or (filtered_segments[0].route if filtered_segments else "全部")

    dates = set()
    for seg in filtered_segments:
        dates.add(seg.start_time.strftime("%Y-%m-%d"))
    date_range = f"{min(dates)}~{max(dates)}" if dates else "无数据"

    high_risk_periods = _build_high_risk_periods(filtered_segments)
    missing_records = _build_missing_driver_records(filtered_segments, trips)
    recommended_wheels = _build_recommended_wheel_checks(filtered_segments)

    return ReviewSummary(
        plate=plate_val,
        route=route_val,
        date_range=date_range,
        high_risk_periods=high_risk_periods,
        missing_driver_records=missing_records,
        recommended_wheel_checks=recommended_wheels,
        anomaly_count=len(filtered_segments),
        raw_segments=filtered_segments,
    )


def _build_high_risk_periods(segments: List[AnomalySegment]) -> List[str]:
    periods: List[str] = []
    for seg in segments:
        risk_tags = []
        if seg.label == AnomalyLabel.TIRE_PRESSURE_DRAG_COOLING:
            risk_tags.append("胎压关联制冷异常")
        if abs(seg.temp_change) >= 5.0:
            risk_tags.append(f"厢温剧烈偏移{seg.temp_change:+.1f}°C")
        if seg.reefer_cycles >= 4:
            risk_tags.append(f"冷机频繁启停{seg.reefer_cycles}次")

        if not risk_tags:
            continue

        time_str = seg.start_time.strftime("%Y-%m-%d %H:%M")
        duration_str = f"{seg.duration_minutes:.0f}min"
        period = (
            f"{time_str}起 持续{duration_str} "
            f"({'+'.join(risk_tags)})"
        )
        periods.append(period)
    return periods


def _build_missing_driver_records(
    segments: List[AnomalySegment], trips: List[Trip]
) -> List[str]:
    records: List[str] = []
    for seg in segments:
        if seg.label == AnomalyLabel.TIRE_PRESSURE_DRAG_COOLING:
            wheels_str = "、".join(seg.abnormal_wheels)
            records.append(
                f"{seg.start_time.strftime('%m-%d %H:%M')} "
                f"胎压异常轮位{wheels_str}未发现司机处置记录"
            )
        if seg.reefer_cycles >= 3:
            records.append(
                f"{seg.start_time.strftime('%m-%d %H:%M')} "
                f"冷机启停{seg.reefer_cycles}次，缺乏手动干预记录"
            )
    return records


def _build_recommended_wheel_checks(segments: List[AnomalySegment]) -> List[str]:
    wheel_counter: Counter = Counter()
    for seg in segments:
        if seg.label in (
            AnomalyLabel.TIRE_PRESSURE_DRAG_COOLING,
            AnomalyLabel.SENSOR_MALFUNCTION,
        ):
            for w in seg.abnormal_wheels:
                wheel_counter[w] += 1

    result: List[str] = []
    for wheel, count in wheel_counter.most_common():
        result.append(f"{wheel} (出现{count}次异常)")
    return result


def export_report(
    summary: ReviewSummary,
    output_dir: str = ".",
    filename: Optional[str] = None,
) -> str:
    if not filename:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        plate_tag = summary.plate.replace(" ", "_")
        route_tag = summary.route.replace(" ", "_")
        filename = f"复盘摘要_{plate_tag}_{route_tag}_{timestamp}.txt"

    os.makedirs(output_dir, exist_ok=True)
    filepath = os.path.join(output_dir, filename)
    report_text = summary.to_text_report()

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(report_text)

    return filepath
