import csv
import json
import os
from datetime import datetime
from typing import Dict, List, Optional

from config import ScreenRules
from models import LogRecord, ReeferStatus, Trip

WHEEL_POSITIONS = ["FL", "FR", "RL", "RR", "FL2", "FR2", "RL2", "RR2"]


def _parse_timestamp(val) -> Optional[datetime]:
    if isinstance(val, datetime):
        return val
    if not val:
        return None
    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y/%m/%d %H:%M:%S",
        "%Y/%m/%d %H:%M",
    ):
        try:
            return datetime.strptime(str(val).strip(), fmt)
        except ValueError:
            continue
    return None


def _parse_float(val) -> Optional[float]:
    if val is None or val == "" or str(val).strip().upper() == "N/A":
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def _parse_reefer_status(val) -> ReeferStatus:
    v = str(val).strip().upper()
    if v in ("ON", "RUNNING", "1", "TRUE"):
        return ReeferStatus.ON
    if v in ("FAULT", "ERROR", "ERR", "2"):
        return ReeferStatus.FAULT
    return ReeferStatus.OFF


def parse_csv_file(filepath: str) -> List[LogRecord]:
    records = []
    with open(filepath, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rec = _row_to_record(row)
            if rec:
                records.append(rec)
    return records


def parse_json_file(filepath: str) -> List[LogRecord]:
    records = []
    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)
    items = data if isinstance(data, list) else [data]
    for item in items:
        rec = _row_to_record(item)
        if rec:
            records.append(rec)
    return records


def _row_to_record(row: Dict) -> Optional[LogRecord]:
    ts = _parse_timestamp(row.get("timestamp") or row.get("time"))
    if not ts:
        return None

    plate = str(row.get("plate") or row.get("车牌") or "").strip()
    route = str(row.get("route") or row.get("线路") or "").strip()
    if not plate:
        return None

    wheels: Dict[str, Optional[float]] = {}
    for pos in WHEEL_POSITIONS:
        for key in (pos, pos.lower(), f"tire_{pos}", f"tire_{pos.lower()}"):
            if key in row:
                wheels[pos] = _parse_float(row[key])
                break

    temp_key = None
    for k in ("compartment_temp", "compartment_temperature", "厢温", "temp"):
        if k in row:
            temp_key = k
            break
    compartment_temp = _parse_float(row[temp_key]) if temp_key else None
    if compartment_temp is None:
        compartment_temp = 0.0

    reefer_key = None
    for k in ("reefer_status", "冷机状态", "reefer"):
        if k in row:
            reefer_key = k
            break
    reefer_status = (
        _parse_reefer_status(row[reefer_key]) if reefer_key else ReeferStatus.OFF
    )

    return LogRecord(
        timestamp=ts,
        plate=plate,
        route=route,
        wheel_positions=wheels,
        compartment_temp=compartment_temp,
        reefer_status=reefer_status,
    )


def load_logs_from_dir(dirpath: str) -> List[LogRecord]:
    all_records: List[LogRecord] = []
    if not os.path.isdir(dirpath):
        return all_records
    for fname in sorted(os.listdir(dirpath)):
        fpath = os.path.join(dirpath, fname)
        if not os.path.isfile(fpath):
            continue
        ext = os.path.splitext(fname)[1].lower()
        try:
            if ext == ".csv":
                all_records.extend(parse_csv_file(fpath))
            elif ext == ".json":
                all_records.extend(parse_json_file(fpath))
        except Exception as e:
            print(f"  [跳过] {fname}: 解析失败 - {e}")
    return all_records


def group_into_trips(records: List[LogRecord], rules: Optional[ScreenRules] = None) -> List[Trip]:
    if not records:
        return []
    gap = (rules.trip_gap_minutes if rules else 30.0)

    groups: Dict[tuple, List[LogRecord]] = {}
    for rec in records:
        key = (rec.plate, rec.route or "")
        groups.setdefault(key, []).append(rec)

    trips: List[Trip] = []
    for (plate, route), group_recs in groups.items():
        sorted_recs = sorted(group_recs, key=lambda r: r.timestamp)
        current = [sorted_recs[0]]
        for i in range(1, len(sorted_recs)):
            delta = (sorted_recs[i].timestamp - sorted_recs[i - 1].timestamp).total_seconds() / 60
            if delta > gap:
                trips.append(
                    Trip(
                        plate=current[0].plate,
                        route=current[0].route,
                        start_time=current[0].timestamp,
                        end_time=current[-1].timestamp,
                        records=list(current),
                    )
                )
                current = [sorted_recs[i]]
            else:
                current.append(sorted_recs[i])
        if current:
            trips.append(
                Trip(
                    plate=current[0].plate,
                    route=current[0].route,
                    start_time=current[0].timestamp,
                    end_time=current[-1].timestamp,
                    records=list(current),
                )
            )
    return sorted(trips, key=lambda t: t.start_time)


def filter_trips(
    trips: List[Trip],
    plate: Optional[str] = None,
    date_str: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    route: Optional[str] = None,
) -> List[Trip]:
    result = trips
    if plate:
        result = [t for t in result if t.plate == plate]
    if date_str:
        result = [t for t in result if t.date_str == date_str]
    if date_from:
        result = [t for t in result if t.date_str >= date_from]
    if date_to:
        result = [t for t in result if t.date_str <= date_to]
    if route:
        result = [t for t in result if t.route == route]
    return result
