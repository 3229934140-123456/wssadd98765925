from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
import csv
import os
from typing import Dict, List, Optional

from config import ScreenRules
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
        if seg.label == AnomalyLabel.SENSOR_MALFUNCTION:
            risk_tags.append("传感器读数异常")

        if not risk_tags:
            continue

        time_str = seg.start_time.strftime("%Y-%m-%d %H:%M")
        duration_str = f"{seg.duration_minutes:.0f}min" if seg.duration_minutes > 0 else "单点"
        period = f"{time_str}起 持续{duration_str} ({'+'.join(risk_tags)})"
        periods.append(period)
    return periods


def _build_missing_driver_records(
    segments: List[AnomalySegment], trips: List[Trip]
) -> List[str]:
    records: List[str] = []
    for seg in segments:
        if seg.label == AnomalyLabel.TIRE_PRESSURE_DRAG_COOLING:
            wheels_str = "、".join(seg.abnormal_wheels) if seg.abnormal_wheels else "异常"
            records.append(
                f"{seg.start_time.strftime('%m-%d %H:%M')} [{seg.plate}] 胎压异常轮位{wheels_str}未发现司机处置记录"
            )
        if seg.reefer_cycles >= 3:
            records.append(
                f"{seg.start_time.strftime('%m-%d %H:%M')} [{seg.plate}] 冷机启停{seg.reefer_cycles}次，缺乏手动干预记录"
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


def _format_report(summary: ReviewSummary, rules: Optional[ScreenRules] = None) -> str:
    lines = []
    lines.append("=" * 60)
    lines.append("冷链运输监控复盘摘要")
    lines.append("=" * 60)
    lines.append(f"车牌: {summary.plate}")
    lines.append(f"线路: {summary.route}")
    lines.append(f"日期范围: {summary.date_range}")
    lines.append(f"异常片段总数: {summary.anomaly_count}")
    lines.append("")

    if rules:
        lines.append("-" * 60)
        lines.append("本次采用筛查规则")
        lines.append("-" * 60)
        lines.append(rules.to_markdown())
        lines.append("")

    lines.append("-" * 60)
    lines.append("高风险时段")
    lines.append("-" * 60)
    if summary.high_risk_periods:
        for p in summary.high_risk_periods:
            lines.append(f"  - {p}")
    else:
        lines.append("  无")

    lines.append("")
    lines.append("-" * 60)
    lines.append("司机处置记录缺失点")
    lines.append("-" * 60)
    if summary.missing_driver_records:
        for m in summary.missing_driver_records:
            lines.append(f"  - {m}")
    else:
        lines.append("  无")

    lines.append("")
    lines.append("-" * 60)
    lines.append("建议复查轮位")
    lines.append("-" * 60)
    if summary.recommended_wheel_checks:
        for w in summary.recommended_wheel_checks:
            lines.append(f"  - {w}")
    else:
        lines.append("  无")

    lines.append("")
    lines.append("-" * 60)
    lines.append("异常片段明细")
    lines.append("-" * 60)
    for seg in summary.raw_segments:
        lines.append(f"  {seg}")
        if seg.detail:
            lines.append(f"    -> {seg.detail}")

    lines.append("")
    lines.append("=" * 60)
    lines.append("报告生成时间: " + datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    lines.append("=" * 60)
    return "\n".join(lines)


def export_report(
    summary: ReviewSummary,
    output_dir: str = ".",
    filename: Optional[str] = None,
    rules: Optional[ScreenRules] = None,
) -> str:
    if not filename:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        plate_tag = summary.plate.replace(" ", "_").replace("/", "_")
        route_tag = summary.route.replace(" ", "_").replace("/", "_")
        filename = f"复盘摘要_{plate_tag}_{route_tag}_{timestamp}.txt"

    os.makedirs(output_dir, exist_ok=True)
    filepath = os.path.join(output_dir, filename)
    report_text = _format_report(summary, rules)

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(report_text)

    return filepath


ANOMALY_CSV_HEADERS = [
    "车牌",
    "线路",
    "开始时间",
    "持续分钟",
    "异常轮位",
    "厢温变化(°C)",
    "冷机启停次数",
    "异常分类",
    "详情",
]


def segment_to_csv_row(seg: AnomalySegment) -> List[str]:
    return [
        seg.plate,
        seg.route,
        seg.start_time.strftime("%Y-%m-%d %H:%M:%S"),
        f"{seg.duration_minutes:.1f}",
        ",".join(seg.abnormal_wheels) if seg.abnormal_wheels else "",
        f"{seg.temp_change:+.2f}",
        str(seg.reefer_cycles),
        seg.label.value,
        seg.detail or "",
    ]


def export_anomaly_csv(
    segments: List[AnomalySegment],
    output_dir: str,
    filename: Optional[str] = None,
    rules: Optional[ScreenRules] = None,
) -> str:
    if not filename:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"异常证据表_{timestamp}.csv"

    os.makedirs(output_dir, exist_ok=True)
    filepath = os.path.join(output_dir, filename)

    with open(filepath, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        if rules:
            writer.writerow(["筛查规则"])
            for rule_line in rules.to_markdown().splitlines():
                writer.writerow([rule_line.strip()])
            writer.writerow([])
        writer.writerow(ANOMALY_CSV_HEADERS)
        for seg in sorted(segments, key=lambda s: s.start_time):
            writer.writerow(segment_to_csv_row(seg))
    return filepath


@dataclass
class BatchReviewResult:
    overview_path: str
    per_vehicle_paths: Dict[str, str]
    evidence_csv_path: str
    total_segments: int
    total_vehicles: int


def build_batch_review(
    dirpath: str,
    output_dir: str,
    rules: ScreenRules,
    trips: List[Trip],
    segments: List[AnomalySegment],
    plate: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    route: Optional[str] = None,
) -> BatchReviewResult:
    from parser import filter_trips as _filter_trips

    scope_trips = _filter_trips(trips, plate=plate, date_from=date_from, date_to=date_to, route=route)
    scope_plates = sorted({t.plate for t in scope_trips})
    scope_segments = [s for s in segments if any(s.plate == t.plate for t in scope_trips)]
    if route:
        scope_segments = [s for s in scope_segments if s.route == route]
    if date_from:
        scope_segments = [s for s in scope_segments if s.start_time.strftime("%Y-%m-%d") >= date_from]
    if date_to:
        scope_segments = [s for s in scope_segments if s.start_time.strftime("%Y-%m-%d") <= date_to]

    os.makedirs(output_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    batch_dir = os.path.join(output_dir, f"批量复盘_{timestamp}")
    os.makedirs(batch_dir, exist_ok=True)
    detail_dir = os.path.join(batch_dir, "单车明细")
    os.makedirs(detail_dir, exist_ok=True)

    per_vehicle_paths: Dict[str, str] = {}
    for p in scope_plates:
        vehicle_segs = [s for s in scope_segments if s.plate == p]
        vehicle_trips = [t for t in scope_trips if t.plate == p]
        routes = sorted({t.route for t in vehicle_trips})
        route_val = route or (routes[0] if len(routes) == 1 else "多条线路")
        summary = build_review_summary(p, route_val, vehicle_trips, vehicle_segs)
        fname = f"复盘摘要_{p}_{route_val}_{timestamp}.txt"
        path = export_report(summary, output_dir=detail_dir, filename=fname, rules=rules)
        per_vehicle_paths[p] = path

    overview_path = _build_overview_file(
        batch_dir,
        scope_plates,
        scope_trips,
        scope_segments,
        rules,
        plate,
        date_from,
        date_to,
        route,
        timestamp,
    )

    csv_path = export_anomaly_csv(
        scope_segments,
        output_dir=batch_dir,
        filename=f"异常证据表_{timestamp}.csv",
        rules=rules,
    )

    return BatchReviewResult(
        overview_path=overview_path,
        per_vehicle_paths=per_vehicle_paths,
        evidence_csv_path=csv_path,
        total_segments=len(scope_segments),
        total_vehicles=len(scope_plates),
    )


def _build_overview_file(
    batch_dir: str,
    plates: List[str],
    trips: List[Trip],
    segments: List[AnomalySegment],
    rules: ScreenRules,
    plate_filter: Optional[str],
    date_from: Optional[str],
    date_to: Optional[str],
    route_filter: Optional[str],
    timestamp: str,
) -> str:
    risk_by_plate: Dict[str, Dict] = defaultdict(lambda: {
        "tire_drag": 0,
        "temp_fluc": 0,
        "sensor": 0,
        "reefer_cycles": 0,
        "trips": 0,
    })

    plate_trips = defaultdict(set)
    for t in trips:
        plate_trips[t.plate].add(t.route)
        risk_by_plate[t.plate]["trips"] += 1

    for seg in segments:
        if seg.label == AnomalyLabel.TIRE_PRESSURE_DRAG_COOLING:
            risk_by_plate[seg.plate]["tire_drag"] += 1
        elif seg.label == AnomalyLabel.PURE_TEMP_FLUCTUATION:
            risk_by_plate[seg.plate]["temp_fluc"] += 1
        elif seg.label == AnomalyLabel.SENSOR_MALFUNCTION:
            risk_by_plate[seg.plate]["sensor"] += 1
        risk_by_plate[seg.plate]["reefer_cycles"] += seg.reefer_cycles

    def _risk_score(data):
        return (
            data["tire_drag"] * 5
            + data["sensor"] * 3
            + data["temp_fluc"] * 1
            + data["reefer_cycles"] * 0.2
        )

    ranked = sorted(plates, key=lambda p: -_risk_score(risk_by_plate[p]))

    lines = []
    lines.append("=" * 70)
    lines.append("月度例会冷链运营批量复盘总览")
    lines.append("=" * 70)
    lines.append(f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("筛选范围:")
    lines.append(f"  车牌: {plate_filter or '全部'}")
    lines.append(f"  线路: {route_filter or '全部'}")
    lines.append(f"  日期: {date_from or '不限'} ~ {date_to or '不限'}")
    lines.append(f"  覆盖车辆数: {len(plates)}  异常片段总数: {len(segments)}")
    lines.append("")

    lines.append("-" * 70)
    lines.append("本次采用筛查规则")
    lines.append("-" * 70)
    lines.append(rules.to_markdown())
    lines.append("")

    lines.append("-" * 70)
    lines.append("风险车辆排名（由高到低）")
    lines.append("-" * 70)
    lines.append(f"{'排名':<4}{'车牌':<12}{'线路':<10}{'行程数':<6}{'胎压拖累制冷':<10}{'温度波动':<8}{'传感器失准':<8}{'冷机启停累计':<12}风险分")
    for rank, p in enumerate(ranked, 1):
        data = risk_by_plate[p]
        routes_str = ",".join(sorted(plate_trips.get(p, set())))
        score = _risk_score(data)
        lines.append(
            f"{rank:<4}{p:<12}{routes_str[:8]:<10}{data['trips']:<6}"
            f"{data['tire_drag']:<10}{data['temp_fluc']:<8}{data['sensor']:<8}"
            f"{data['reefer_cycles']:<12}{score:.1f}"
        )

    lines.append("")
    lines.append("-" * 70)
    lines.append("高风险提示 TOP5")
    lines.append("-" * 70)
    top = ranked[:5]
    if top:
        for idx, p in enumerate(top, 1):
            data = risk_by_plate[p]
            tips = []
            if data["tire_drag"] > 0:
                tips.append(f"{data['tire_drag']}次胎压拖累制冷")
            if data["sensor"] > 0:
                tips.append(f"{data['sensor']}次传感器失准")
            if data["reefer_cycles"] >= 5:
                tips.append(f"冷机启停累计{data['reefer_cycles']}次")
            if not tips:
                tips.append("未发现重大异常")
            lines.append(f"  {idx}. [{p}] " + "；".join(tips))
    else:
        lines.append("  无")

    lines.append("")
    lines.append("-" * 70)
    lines.append("附件清单")
    lines.append("-" * 70)
    lines.append(f"  - 单车明细: ./单车明细/ 目录下共{len(plates)}份文本报告")
    lines.append(f"  - 异常证据表CSV: ./异常证据表_{timestamp}.csv")
    lines.append("")
    lines.append("=" * 70)

    filepath = os.path.join(batch_dir, f"复盘总览_{timestamp}.txt")
    with open(filepath, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return filepath
