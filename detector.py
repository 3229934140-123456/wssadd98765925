from typing import List, Optional, Set

from models import AnomalyLabel, AnomalySegment, LogRecord, Trip

TIRE_LOW = 4.5
TIRE_HIGH = 8.0
TEMP_FLUCTUATION = 3.0
SENSOR_JUMP_PRESSURE = 3.0
SENSOR_JUMP_TEMP = 10.0
MIN_SEGMENT_MINUTES = 2


def _count_reefer_cycles(records: List[LogRecord]) -> int:
    cycles = 0
    for i in range(1, len(records)):
        if records[i].reefer_status != records[i - 1].reefer_status:
            cycles += 1
    return cycles


def _collect_abnormal_wheels(records: List[LogRecord]) -> Set[str]:
    wheels: Set[str] = set()
    for rec in records:
        wheels.update(rec.is_tire_pressure_abnormal(TIRE_LOW, TIRE_HIGH))
    return wheels


def _temp_change(records: List[LogRecord]) -> float:
    if len(records) < 2:
        return 0.0
    temps = [r.compartment_temp for r in records]
    return temps[-1] - temps[0]


def _detect_sensor_jumps(prev: Optional[LogRecord], curr: LogRecord) -> bool:
    if prev is None:
        return False
    for pos in curr.wheel_positions:
        if pos in prev.wheel_positions:
            cv = curr.wheel_positions[pos]
            pv = prev.wheel_positions[pos]
            if cv is not None and pv is not None:
                if abs(cv - pv) > SENSOR_JUMP_PRESSURE:
                    return True
    if abs(curr.compartment_temp - prev.compartment_temp) > SENSOR_JUMP_TEMP:
        return True
    return False


def _classify_anomaly(
    has_tire_issue: bool,
    temp_delta: float,
    reefer_cycles: int,
    sensor_jump: bool,
) -> AnomalyLabel:
    if sensor_jump:
        return AnomalyLabel.SENSOR_MALFUNCTION
    if has_tire_issue and (abs(temp_delta) >= TEMP_FLUCTUATION or reefer_cycles >= 2):
        return AnomalyLabel.TIRE_PRESSURE_DRAG_COOLING
    if has_tire_issue:
        return AnomalyLabel.TIRE_PRESSURE_DRAG_COOLING
    return AnomalyLabel.PURE_TEMP_FLUCTUATION


def _build_detail(
    label: AnomalyLabel,
    abnormal_wheels: List[str],
    temp_delta: float,
    reefer_cycles: int,
) -> str:
    if label == AnomalyLabel.TIRE_PRESSURE_DRAG_COOLING:
        wheels_str = "、".join(abnormal_wheels)
        return (
            f"轮位{wheels_str}胎压异常，厢温偏移{temp_delta:+.1f}°C，"
            f"冷机频繁启停{reefer_cycles}次，疑似胎压问题拖累制冷效率"
        )
    if label == AnomalyLabel.SENSOR_MALFUNCTION:
        return "相邻采样点数值跳变过大，传感器读数可能失准，建议校验"
    return (
        f"厢温波动{temp_delta:+.1f}°C，冷机启停{reefer_cycles}次，"
        f"未关联胎压异常，属单纯温度波动"
    )


def detect_anomalies(trip: Trip) -> List[AnomalySegment]:
    if len(trip.records) < 2:
        return []

    segments: List[AnomalySegment] = []
    buf: List[LogRecord] = []
    in_anomaly = False
    prev_rec: Optional[LogRecord] = None

    for rec in trip.records:
        tire_abnormal = rec.is_tire_pressure_abnormal(TIRE_LOW, TIRE_HIGH)
        temp_abnormal = (
            prev_rec is not None
            and abs(rec.compartment_temp - prev_rec.compartment_temp) >= TEMP_FLUCTUATION
        )
        sensor_jump = _detect_sensor_jumps(prev_rec, rec)
        is_anomaly = bool(tire_abnormal) or temp_abnormal or sensor_jump

        if is_anomaly:
            if not in_anomaly:
                buf = [rec]
                in_anomaly = True
            else:
                buf.append(rec)
        else:
            if in_anomaly:
                seg = _finalize_segment(buf, trip)
                if seg:
                    segments.append(seg)
                buf = []
                in_anomaly = False

        prev_rec = rec

    if in_anomaly and buf:
        seg = _finalize_segment(buf, trip)
        if seg:
            segments.append(seg)

    return segments


def _finalize_segment(buf: List[LogRecord], trip: Trip) -> Optional[AnomalySegment]:
    if not buf:
        return None
    start = buf[0].timestamp
    end = buf[-1].timestamp
    duration = (end - start).total_seconds() / 60.0
    if duration < MIN_SEGMENT_MINUTES:
        return None

    abnormal_wheels = sorted(_collect_abnormal_wheels(buf))
    temp_delta = _temp_change(buf)
    reefer_cycles = _count_reefer_cycles(buf)
    has_tire = len(abnormal_wheels) > 0
    has_jump = any(
        _detect_sensor_jumps(buf[i - 1], buf[i]) for i in range(1, len(buf))
    )
    label = _classify_anomaly(has_tire, temp_delta, reefer_cycles, has_jump)
    detail = _build_detail(label, abnormal_wheels, temp_delta, reefer_cycles)

    return AnomalySegment(
        start_time=start,
        duration_minutes=duration,
        abnormal_wheels=abnormal_wheels,
        temp_change=temp_delta,
        reefer_cycles=reefer_cycles,
        label=label,
        plate=trip.plate,
        route=trip.route,
        detail=detail,
    )


def detect_all_trips(trips: List[Trip]) -> List[AnomalySegment]:
    all_segments: List[AnomalySegment] = []
    for trip in trips:
        all_segments.extend(detect_anomalies(trip))
    return sorted(all_segments, key=lambda s: s.start_time)
