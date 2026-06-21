from dataclasses import dataclass
from typing import List, Optional, Set

from config import ScreenRules
from models import AnomalyLabel, AnomalySegment, LogRecord, Trip


@dataclass
class JumpSnapshot:
    wheel: str = ""
    before: Optional[float] = None
    after: Optional[float] = None
    delta: float = 0.0
    kind: str = ""


def _count_reefer_cycles(records: List[LogRecord]) -> int:
    cycles = 0
    for i in range(1, len(records)):
        if records[i].reefer_status != records[i - 1].reefer_status:
            cycles += 1
    return cycles


def _collect_abnormal_wheels(records: List[LogRecord], rules: ScreenRules) -> Set[str]:
    wheels: Set[str] = set()
    for rec in records:
        wheels.update(rec.is_tire_pressure_abnormal(rules.tire_low, rules.tire_high))
    return wheels


def _temp_change(records: List[LogRecord]) -> float:
    if len(records) < 2:
        return 0.0
    temps = [r.compartment_temp for r in records]
    return temps[-1] - temps[0]


def _detect_sensor_jumps(prev: Optional[LogRecord], curr: LogRecord, rules: ScreenRules):
    snapshot: List[JumpSnapshot] = []
    if prev is None:
        return snapshot, False

    for pos in curr.wheel_positions:
        if pos in prev.wheel_positions:
            cv = curr.wheel_positions[pos]
            pv = prev.wheel_positions[pos]
            if cv is not None and pv is not None:
                delta = cv - pv
                if abs(delta) > rules.sensor_jump_pressure:
                    snapshot.append(
                        JumpSnapshot(wheel=pos, before=pv, after=cv, delta=delta, kind="胎压跳变")
                    )

    temp_delta = curr.compartment_temp - prev.compartment_temp
    if abs(temp_delta) > rules.sensor_jump_temp:
        snapshot.append(
            JumpSnapshot(
                wheel="厢温",
                before=prev.compartment_temp,
                after=curr.compartment_temp,
                delta=temp_delta,
                kind="温度跳变",
            )
        )
    return snapshot, bool(snapshot)


def _classify_anomaly(
    has_tire_issue: bool,
    temp_delta: float,
    reefer_cycles: int,
    sensor_jump: bool,
    rules: ScreenRules,
) -> AnomalyLabel:
    if sensor_jump:
        return AnomalyLabel.SENSOR_MALFUNCTION
    if has_tire_issue and (abs(temp_delta) >= rules.temp_fluctuation or reefer_cycles >= 2):
        return AnomalyLabel.TIRE_PRESSURE_DRAG_COOLING
    if has_tire_issue:
        return AnomalyLabel.TIRE_PRESSURE_DRAG_COOLING
    return AnomalyLabel.PURE_TEMP_FLUCTUATION


def _build_detail(
    label: AnomalyLabel,
    abnormal_wheels: List[str],
    temp_delta: float,
    reefer_cycles: int,
    jumps: List[JumpSnapshot],
) -> str:
    if label == AnomalyLabel.SENSOR_MALFUNCTION and jumps:
        parts = []
        for j in jumps:
            before_str = f"{j.before:.1f}" if j.before is not None else "N/A"
            after_str = f"{j.after:.1f}" if j.after is not None else "N/A"
            unit = "bar" if j.kind == "胎压跳变" else "°C"
            target = j.wheel if j.kind == "胎压跳变" else "厢温"
            parts.append(
                f"{target}{before_str}{unit}→{after_str}{unit}(Δ{j.delta:+.1f})"
            )
        jumps_str = "；".join(parts)
        return f"{jumps_str}。建议复核：检查传感器线缆、采集频率及前后采样读数。"
    if label == AnomalyLabel.TIRE_PRESSURE_DRAG_COOLING:
        wheels_str = "、".join(abnormal_wheels)
        return (
            f"轮位{wheels_str}胎压异常，厢温偏移{temp_delta:+.1f}°C，"
            f"冷机启停{reefer_cycles}次，疑似胎压拖累制冷效率。建议复核：轮位实际气压、冷机制冷电流。"
        )
    return (
        f"厢温波动{temp_delta:+.1f}°C，冷机启停{reefer_cycles}次，未关联胎压异常。"
        f"建议复核：开门记录、环境温度、装载作业。"
    )


def detect_anomalies(trip: Trip, rules: ScreenRules) -> List[AnomalySegment]:
    if len(trip.records) < 2:
        return []

    segments: List[AnomalySegment] = []
    buf: List[LogRecord] = []
    in_anomaly = False
    prev_rec: Optional[LogRecord] = None
    all_jumps: List[JumpSnapshot] = []

    for rec in trip.records:
        tire_abnormal = rec.is_tire_pressure_abnormal(rules.tire_low, rules.tire_high)
        temp_abnormal = (
            prev_rec is not None
            and abs(rec.compartment_temp - prev_rec.compartment_temp) >= rules.temp_fluctuation
        )
        jumps, sensor_jump = _detect_sensor_jumps(prev_rec, rec, rules)
        is_anomaly = bool(tire_abnormal) or temp_abnormal or sensor_jump

        if is_anomaly:
            all_jumps.extend(jumps)
            if not in_anomaly:
                buf = [rec]
                in_anomaly = True
            else:
                buf.append(rec)
        else:
            if in_anomaly:
                seg = _finalize_segment(buf, trip, rules, all_jumps)
                if seg:
                    segments.append(seg)
                buf = []
                all_jumps = []
                in_anomaly = False

        prev_rec = rec

    if in_anomaly and buf:
        seg = _finalize_segment(buf, trip, rules, all_jumps)
        if seg:
            segments.append(seg)

    if rules.enable_single_point_anomaly:
        segments = sorted(segments, key=lambda s: s.start_time)
        covered_ranges = []
        for seg in segments:
            if seg.duration_minutes > 0:
                from datetime import timedelta
                end = seg.start_time + timedelta(minutes=seg.duration_minutes)
                covered_ranges.append((seg.start_time, end))

        def _is_covered(ts) -> bool:
            for start, end in covered_ranges:
                if start <= ts <= end:
                    return True
            return False

        for i in range(1, len(trip.records)):
            jumps, sensor_jump = _detect_sensor_jumps(trip.records[i - 1], trip.records[i], rules)
            tire_abnormal = trip.records[i].is_tire_pressure_abnormal(
                rules.tire_low, rules.tire_high
            )
            ts = trip.records[i].timestamp
            if (sensor_jump or tire_abnormal) and not _is_covered(ts):
                seg = _build_single_point_segment(trip.records[i - 1], trip.records[i], trip, rules, jumps)
                if seg:
                    segments.append(seg)

    return sorted(segments, key=lambda s: s.start_time)


def _build_single_point_segment(
    prev: LogRecord,
    curr: LogRecord,
    trip: Trip,
    rules: ScreenRules,
    jumps: List[JumpSnapshot],
) -> Optional[AnomalySegment]:
    tire_abnormal = curr.is_tire_pressure_abnormal(rules.tire_low, rules.tire_high)
    temp_delta = curr.compartment_temp - prev.compartment_temp
    wheels = sorted(set(tire_abnormal) | {j.wheel for j in jumps if j.kind == "胎压跳变"})
    has_jump = bool(jumps)
    label = _classify_anomaly(bool(wheels), temp_delta, 0, has_jump, rules)
    detail = _build_detail(label, wheels, temp_delta, 0, jumps)
    return AnomalySegment(
        start_time=curr.timestamp,
        duration_minutes=0.0,
        abnormal_wheels=wheels,
        temp_change=temp_delta,
        reefer_cycles=0,
        label=label,
        plate=trip.plate,
        route=trip.route,
        detail=detail,
    )


def _finalize_segment(
    buf: List[LogRecord],
    trip: Trip,
    rules: ScreenRules,
    jumps: List[JumpSnapshot],
) -> Optional[AnomalySegment]:
    if not buf:
        return None
    start = buf[0].timestamp
    end = buf[-1].timestamp
    duration = (end - start).total_seconds() / 60.0
    if duration < rules.min_segment_minutes and not rules.enable_single_point_anomaly:
        return None

    abnormal_wheels = sorted(_collect_abnormal_wheels(buf, rules))
    temp_delta = _temp_change(buf)
    reefer_cycles = _count_reefer_cycles(buf)
    has_tire = len(abnormal_wheels) > 0
    has_jump = any(
        _detect_sensor_jumps(buf[i - 1], buf[i], rules)[1]
        for i in range(1, len(buf))
    )
    label = _classify_anomaly(has_tire, temp_delta, reefer_cycles, has_jump, rules)
    detail = _build_detail(label, abnormal_wheels, temp_delta, reefer_cycles, jumps)

    return AnomalySegment(
        start_time=start,
        duration_minutes=max(duration, 0.0),
        abnormal_wheels=abnormal_wheels,
        temp_change=temp_delta,
        reefer_cycles=reefer_cycles,
        label=label,
        plate=trip.plate,
        route=trip.route,
        detail=detail,
    )


def detect_all_trips(trips: List[Trip], rules: ScreenRules) -> List[AnomalySegment]:
    all_segments: List[AnomalySegment] = []
    for trip in trips:
        all_segments.extend(detect_anomalies(trip, rules))
    seen = set()
    unique: List[AnomalySegment] = []
    for seg in sorted(all_segments, key=lambda s: s.start_time):
        key = (seg.plate, seg.route, seg.start_time, seg.label.value)
        if key in seen:
            continue
        seen.add(key)
        unique.append(seg)
    return unique
