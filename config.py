import copy
import json
import os
from dataclasses import asdict, dataclass
from typing import Dict, Optional


@dataclass
class ScreenRules:
    tire_low: float = 4.5
    tire_high: float = 8.0
    temp_fluctuation: float = 3.0
    sensor_jump_pressure: float = 3.0
    sensor_jump_temp: float = 10.0
    trip_gap_minutes: float = 30.0
    min_segment_minutes: float = 2.0
    enable_single_point_anomaly: bool = True
    route_overrides: Dict[str, dict] = None

    def __post_init__(self):
        if self.route_overrides is None:
            self.route_overrides = {}

    def rules_for_route(self, route: Optional[str]) -> "ScreenRules":
        if not route or route not in self.route_overrides:
            base = copy.deepcopy(self)
            base.route_overrides = {}
            return base
        overrides = self.route_overrides[route]
        base = copy.deepcopy(self)
        base.route_overrides = {}
        for key, val in overrides.items():
            if hasattr(base, key):
                setattr(base, key, val)
        return base

    def to_markdown(self, route: Optional[str] = None) -> str:
        effective = self.rules_for_route(route)
        source = "默认规则"
        if route and route in self.route_overrides:
            source = f"线路{route}专用规则(覆盖默认)"
        lines = [
            f"  规则来源: {source}",
            f"  胎压下限: {effective.tire_low} bar",
            f"  胎压上限: {effective.tire_high} bar",
            f"  温度波动阈值: ±{effective.temp_fluctuation}°C",
            f"  胎压传感器跳变阈值: {effective.sensor_jump_pressure} bar",
            f"  温度传感器跳变阈值: {effective.sensor_jump_temp}°C",
            f"  行程切分间隔: {effective.trip_gap_minutes} min",
            f"  最短异常片段时长: {effective.min_segment_minutes} min",
            f"  启用单点异常保留: {'是' if effective.enable_single_point_anomaly else '否'}",
        ]
        if self.route_overrides:
            lines.append(f"  已配置线路覆盖: {', '.join(sorted(self.route_overrides.keys()))}")
        return "\n".join(lines)


DEFAULT_CONFIG_FILENAMES = ["coldchain_config.json", "config.json"]


def find_default_config(cwd: Optional[str] = None) -> Optional[str]:
    base = cwd or os.getcwd()
    for fname in DEFAULT_CONFIG_FILENAMES:
        path = os.path.join(base, fname)
        if os.path.isfile(path):
            return path
    return None


def load_config(path: Optional[str] = None) -> ScreenRules:
    rules = ScreenRules()
    target = path or find_default_config()
    if not target or not os.path.isfile(target):
        return rules
    try:
        with open(target, "r", encoding="utf-8") as f:
            data = json.load(f)
        for key, val in data.items():
            if hasattr(rules, key):
                setattr(rules, key, val)
    except Exception as e:
        print(f"  [警告] 读取配置文件失败，使用默认值: {e}")
    return rules


def apply_cli_overrides(rules: ScreenRules, overrides: dict) -> ScreenRules:
    for key, val in overrides.items():
        if val is not None and hasattr(rules, key):
            setattr(rules, key, val)
    return rules


def save_default_config(path: str) -> str:
    data = {
        "tire_low": 4.5,
        "tire_high": 8.0,
        "temp_fluctuation": 3.0,
        "sensor_jump_pressure": 3.0,
        "sensor_jump_temp": 10.0,
        "trip_gap_minutes": 30.0,
        "min_segment_minutes": 2.0,
        "enable_single_point_anomaly": True,
        "route_overrides": {
            "R001": {
                "tire_low": 5.0,
                "tire_high": 8.5,
                "comment": "干线长途，胎压要求更严"
            },
            "R007": {
                "tire_low": 4.0,
                "temp_fluctuation": 4.0,
                "comment": "市配短途，放宽温度跳变口径"
            }
        },
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return path
