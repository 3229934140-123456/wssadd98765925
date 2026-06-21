from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
import csv
import os
from typing import Dict, List, Optional, Tuple

from config import ScreenRules
from models import AnomalyLabel, AnomalySegment, ReviewSummary, Trip


def build_review_summary(
    plate: Optional[str],
    route: Optional[str],
    trips: List[Trip],
    segments: List[AnomalySegment],
    rules: Optional[ScreenRules] = None,
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


def _format_report(summary: ReviewSummary, rules: Optional[ScreenRules] = None, route: Optional[str] = None) -> str:
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
        lines.append(rules.to_markdown(route))
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
    route: Optional[str] = None,
) -> str:
    if not filename:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        plate_tag = summary.plate.replace(" ", "_").replace("/", "_")
        route_tag = summary.route.replace(" ", "_").replace("/", "_")
        filename = f"复盘摘要_{plate_tag}_{route_tag}_{timestamp}.txt"

    os.makedirs(output_dir, exist_ok=True)
    filepath = os.path.join(output_dir, filename)
    report_text = _format_report(summary, rules, route)

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
    route: Optional[str] = None,
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
            for rule_line in rules.to_markdown(route).splitlines():
                writer.writerow([rule_line.strip()])
            writer.writerow([])
        writer.writerow(ANOMALY_CSV_HEADERS)
        for seg in sorted(segments, key=lambda s: s.start_time):
            writer.writerow(segment_to_csv_row(seg))
    return filepath


def _risk_score(data: Dict) -> float:
    return (
        data.get("tire_drag", 0) * 5
        + data.get("sensor", 0) * 3
        + data.get("temp_fluc", 0) * 1
        + data.get("reefer_cycles", 0) * 0.2
    )


def _compute_risk_by_plate(
    trips: List[Trip],
    segments: List[AnomalySegment],
) -> Tuple[Dict[str, Dict], Dict[str, set]]:
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

    return risk_by_plate, plate_trips


def _compute_risk_by_route(
    trips: List[Trip],
    segments: List[AnomalySegment],
) -> Dict[str, Dict]:
    risk_by_route: Dict[str, Dict] = defaultdict(lambda: {
        "tire_drag": 0,
        "temp_fluc": 0,
        "sensor": 0,
        "anomaly_total": 0,
        "vehicles": set(),
    })
    for t in trips:
        risk_by_route[t.route]["vehicles"].add(t.plate)

    for seg in segments:
        risk_by_route[seg.route]["anomaly_total"] += 1
        if seg.label == AnomalyLabel.TIRE_PRESSURE_DRAG_COOLING:
            risk_by_route[seg.route]["tire_drag"] += 1
        elif seg.label == AnomalyLabel.PURE_TEMP_FLUCTUATION:
            risk_by_route[seg.route]["temp_fluc"] += 1
        elif seg.label == AnomalyLabel.SENSOR_MALFUNCTION:
            risk_by_route[seg.route]["sensor"] += 1

    return risk_by_route


def _compute_trend(
    current_risk: Dict[str, Dict],
    prev_risk: Optional[Dict[str, Dict]],
) -> Dict[str, Dict]:
    if prev_risk is None:
        return {}

    trend: Dict[str, Dict] = {}
    all_plates = set(current_risk.keys()) | set(prev_risk.keys())
    for plate in all_plates:
        cur = current_risk.get(plate, {"tire_drag": 0, "temp_fluc": 0, "sensor": 0, "reefer_cycles": 0})
        prv = prev_risk.get(plate, {"tire_drag": 0, "temp_fluc": 0, "sensor": 0, "reefer_cycles": 0})
        cur_score = _risk_score(cur)
        prv_score = _risk_score(prv)
        cur_total = cur["tire_drag"] + cur["temp_fluc"] + cur["sensor"]
        prv_total = prv["tire_drag"] + prv["temp_fluc"] + prv["sensor"]
        trend[plate] = {
            "cur_anomaly": cur_total,
            "prv_anomaly": prv_total,
            "anomaly_delta": cur_total - prv_total,
            "cur_score": cur_score,
            "prv_score": prv_score,
            "score_delta": cur_score - prv_score,
        }
    return trend


@dataclass
class BatchReviewResult:
    overview_path: str
    markdown_path: str
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
    prev_trips: Optional[List[Trip]] = None,
    prev_segments: Optional[List[AnomalySegment]] = None,
    prev_date_from: Optional[str] = None,
    prev_date_to: Optional[str] = None,
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
        vehicle_routes = sorted({t.route for t in vehicle_trips})
        route_val = route or (vehicle_routes[0] if len(vehicle_routes) == 1 else "多条线路")
        effective_route = route_val if route_val != "多条线路" else None
        summary = build_review_summary(p, route_val, vehicle_trips, vehicle_segs, rules)
        fname = f"复盘摘要_{p}_{route_val}_{timestamp}.txt"
        path = export_report(summary, output_dir=detail_dir, filename=fname, rules=rules, route=effective_route)
        per_vehicle_paths[p] = path

    risk_by_plate, plate_trips = _compute_risk_by_plate(scope_trips, scope_segments)
    risk_by_route = _compute_risk_by_route(scope_trips, scope_segments)

    prev_risk = None
    trend = {}
    if prev_trips is not None and prev_segments is not None:
        prev_scope = _filter_trips(prev_trips, plate=plate, date_from=prev_date_from, date_to=prev_date_to, route=route)
        prev_scope_segs = [s for s in prev_segments if any(s.plate == t.plate for t in prev_scope)]
        if route:
            prev_scope_segs = [s for s in prev_scope_segs if s.route == route]
        prev_risk, _ = _compute_risk_by_plate(prev_scope, prev_scope_segs)
        trend = _compute_trend(risk_by_plate, prev_risk)

    overview_path = _build_overview_file(
        batch_dir, scope_plates, scope_trips, scope_segments, rules,
        plate, date_from, date_to, route, timestamp,
        risk_by_plate, plate_trips, risk_by_route, trend,
        prev_date_from, prev_date_to,
    )

    md_path = _build_markdown_file(
        batch_dir, scope_plates, scope_trips, scope_segments, rules,
        plate, date_from, date_to, route, timestamp,
        risk_by_plate, plate_trips, risk_by_route, trend,
        prev_date_from, prev_date_to,
    )

    csv_path = export_anomaly_csv(
        scope_segments,
        output_dir=batch_dir,
        filename=f"异常证据表_{timestamp}.csv",
        rules=rules,
        route=route,
    )

    return BatchReviewResult(
        overview_path=overview_path,
        markdown_path=md_path,
        per_vehicle_paths=per_vehicle_paths,
        evidence_csv_path=csv_path,
        total_segments=len(scope_segments),
        total_vehicles=len(scope_plates),
    )


def _build_overview_file(
    batch_dir, plates, trips, segments, rules,
    plate_filter, date_from, date_to, route_filter, timestamp,
    risk_by_plate, plate_trips, risk_by_route, trend,
    prev_date_from, prev_date_to,
) -> str:
    ranked = sorted(plates, key=lambda p: -_risk_score(risk_by_plate[p]))

    lines = []
    lines.append("=" * 70)
    lines.append("月度例会冷链运营批量复盘总览")
    lines.append("=" * 70)
    lines.append(f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("筛选范围:")
    lines.append(f"  车牌: {plate_filter or '全部'}")
    lines.append(f"  线路: {route_filter or '全部'}")
    lines.append(f"  当期: {date_from or '不限'} ~ {date_to or '不限'}")
    if prev_date_from or prev_date_to:
        lines.append(f"  对比期: {prev_date_from or '不限'} ~ {prev_date_to or '不限'}")
    lines.append(f"  覆盖车辆数: {len(plates)}  异常片段总数: {len(segments)}")
    lines.append("")

    lines.append("-" * 70)
    lines.append("本次采用筛查规则")
    lines.append("-" * 70)
    lines.append(rules.to_markdown(route_filter))
    lines.append("")

    lines.append("-" * 70)
    lines.append("风险车辆排名（由高到低）")
    lines.append("-" * 70)
    header = f"{'排名':<4}{'车牌':<12}{'线路':<10}{'行程':<4}{'胎压拖累':<8}{'温度波动':<8}{'传感器':<6}{'启停':<4}{'风险分':<6}"
    if trend:
        header += f"{'异常Δ':<6}{'风险Δ':<6}"
    lines.append(header)
    for rank, p in enumerate(ranked, 1):
        data = risk_by_plate[p]
        routes_str = ",".join(sorted(plate_trips.get(p, set())))
        score = _risk_score(data)
        row = (
            f"{rank:<4}{p:<12}{routes_str[:8]:<10}{data['trips']:<4}"
            f"{data['tire_drag']:<8}{data['temp_fluc']:<8}{data['sensor']:<6}"
            f"{data['reefer_cycles']:<4}{score:<6.1f}"
        )
        if trend and p in trend:
            t = trend[p]
            row += f"{t['anomaly_delta']:+d}{'':>2}{t['score_delta']:+.1f}"
        lines.append(row)

    if trend:
        lines.append("")
        lines.append("-" * 70)
        lines.append("月度趋势对比（对比期→当期）")
        lines.append("-" * 70)
        for p in sorted(trend.keys(), key=lambda x: -trend[x]["score_delta"]):
            t = trend[p]
            arrow = "↑" if t["score_delta"] > 0 else ("↓" if t["score_delta"] < 0 else "→")
            lines.append(
                f"  [{p}] 异常{t['prv_anomaly']}→{t['cur_anomaly']}({t['anomaly_delta']:+d}) "
                f"风险{t['prv_score']:.1f}→{t['cur_score']:.1f}({t['score_delta']:+.1f}) {arrow}"
            )

    lines.append("")
    lines.append("-" * 70)
    lines.append("线路汇总")
    lines.append("-" * 70)
    for r in sorted(risk_by_route.keys()):
        rd = risk_by_route[r]
        lines.append(
            f"  {r}: {rd['anomaly_total']}个异常, "
            f"胎压拖累{rd['tire_drag']} 温度波动{rd['temp_fluc']} 传感器{rd['sensor']} "
            f"覆盖{len(rd['vehicles'])}辆车"
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
            if trend and p in trend and trend[p]["score_delta"] > 0:
                tips.append(f"风险分较上期+{trend[p]['score_delta']:.1f}")
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
    lines.append(f"  - Markdown总览: ./复盘总览_{timestamp}.md")
    lines.append(f"  - 异常证据表CSV: ./异常证据表_{timestamp}.csv")
    lines.append("")
    lines.append("=" * 70)

    filepath = os.path.join(batch_dir, f"复盘总览_{timestamp}.txt")
    with open(filepath, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return filepath


def _build_markdown_file(
    batch_dir, plates, trips, segments, rules,
    plate_filter, date_from, date_to, route_filter, timestamp,
    risk_by_plate, plate_trips, risk_by_route, trend,
    prev_date_from, prev_date_to,
) -> str:
    ranked = sorted(plates, key=lambda p: -_risk_score(risk_by_plate[p]))

    md = []
    md.append("# 🚛 冷链运营月度复盘总览\n")
    md.append(f"> 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")

    md.append("## 筛选范围\n")
    md.append(f"- 车牌: {plate_filter or '全部'}")
    md.append(f"- 线路: {route_filter or '全部'}")
    md.append(f"- 当期: {date_from or '不限'} ~ {date_to or '不限'}")
    if prev_date_from or prev_date_to:
        md.append(f"- 对比期: {prev_date_from or '不限'} ~ {prev_date_to or '不限'}")
    md.append(f"- 覆盖车辆: **{len(plates)}** 辆 | 异常片段: **{len(segments)}** 个\n")

    md.append("## 筛查规则\n")
    for line in rules.to_markdown(route_filter).splitlines():
        md.append(line.strip())
    md.append("")

    md.append("## ⚠️ 风险车辆排名\n")
    if trend:
        md.append("| 排名 | 车牌 | 线路 | 行程 | 胎压拖累 | 温度波动 | 传感器 | 启停 | 风险分 | 异常Δ | 风险Δ |")
        md.append("|------|------|------|------|----------|----------|--------|------|--------|--------|--------|")
    else:
        md.append("| 排名 | 车牌 | 线路 | 行程 | 胎压拖累 | 温度波动 | 传感器 | 启停 | 风险分 |")
        md.append("|------|------|------|------|----------|----------|--------|------|--------|")

    for rank, p in enumerate(ranked, 1):
        data = risk_by_plate[p]
        routes_str = ",".join(sorted(plate_trips.get(p, set())))
        score = _risk_score(data)
        row = f"| {rank} | {p} | {routes_str} | {data['trips']} | {data['tire_drag']} | {data['temp_fluc']} | {data['sensor']} | {data['reefer_cycles']} | {score:.1f} |"
        if trend and p in trend:
            t = trend[p]
            row += f" {t['anomaly_delta']:+d} | {t['score_delta']:+.1f} |"
        md.append(row)
    md.append("")

    if trend:
        md.append("## 📊 月度趋势对比\n")
        md.append("| 车牌 | 上期异常 | 当期异常 | 变化 | 上期风险 | 当期风险 | 变化 | 趋势 |")
        md.append("|------|----------|----------|------|----------|----------|------|------|")
        for p in sorted(trend.keys(), key=lambda x: -trend[x]["score_delta"]):
            t = trend[p]
            arrow = "🔴↑" if t["score_delta"] > 0 else ("🟢↓" if t["score_delta"] < 0 else "➡️→")
            md.append(
                f"| {p} | {t['prv_anomaly']} | {t['cur_anomaly']} | {t['anomaly_delta']:+d} | "
                f"{t['prv_score']:.1f} | {t['cur_score']:.1f} | {t['score_delta']:+.1f} | {arrow} |"
            )
        md.append("")

    md.append("## 🛣️ 线路汇总\n")
    md.append("| 线路 | 异常总数 | 胎压拖累 | 温度波动 | 传感器 | 覆盖车辆 |")
    md.append("|------|----------|----------|----------|--------|----------|")
    for r in sorted(risk_by_route.keys()):
        rd = risk_by_route[r]
        md.append(
            f"| {r} | {rd['anomaly_total']} | {rd['tire_drag']} | {rd['temp_fluc']} | {rd['sensor']} | {len(rd['vehicles'])} |"
        )
    md.append("")

    md.append("## 🔥 重点异常摘要\n")
    high_segs = [
        s for s in segments
        if s.label in (AnomalyLabel.TIRE_PRESSURE_DRAG_COOLING, AnomalyLabel.SENSOR_MALFUNCTION)
        or abs(s.temp_change) >= 5.0
        or s.reefer_cycles >= 4
    ]
    if high_segs:
        for seg in high_segs[:10]:
            icon = {"疑似胎压拖累制冷": "⚠️", "传感器可能失准": "✖️", "单纯温度波动": "△"}.get(seg.label.value, "⚠️")
            md.append(f"- {icon} **[{seg.plate}] {seg.route}** {seg.start_time.strftime('%m-%d %H:%M')} | {seg.label.value} | {seg.detail}")
    else:
        md.append("- 无重大异常")
    md.append("")

    md.append("## 📎 附件\n")
    md.append(f"- 单车明细: `./单车明细/` 目录下共{len(plates)}份文本报告")
    md.append(f"- 异常证据表: `./异常证据表_{timestamp}.csv`")
    md.append("")

    md.append("---")
    md.append(f"*冷链运营数据核对工具 v1.2 | {datetime.now().strftime('%Y-%m-%d')}*")

    filepath = os.path.join(batch_dir, f"复盘总览_{timestamp}.md")
    with open(filepath, "w", encoding="utf-8") as f:
        f.write("\n".join(md))
    return filepath
