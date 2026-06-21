import copy
import json
import os
from dataclasses import asdict, dataclass
from typing import Dict, Optional


RULE_KEYS = [
    "tire_low",
    "tire_high",
    "temp_fluctuation",
    "sensor_jump_pressure",
    "sensor_jump_temp",
    "trip_gap_minutes",
    "min_segment_minutes",
    "enable_single_point_anomaly",
]


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
    _cli_overrides: Dict[str, bool] = None

    def __post_init__(self):
        if self.route_overrides is None:
            self.route_overrides = {}
        if self._cli_overrides is None:
            self._cli_overrides = {}

    def _apply_cli_overrides(self, overrides: dict):
        for key, val in overrides.items():
            if val is not None and key in RULE_KEYS:
                setattr(self, key, val)
                self._cli_overrides[key] = True

    def rules_for_route(self, route: Optional[str]) -> "ScreenRules":
        base = copy.deepcopy(self)
        base.route_overrides = {}
        cli_flags = dict(base._cli_overrides)
        base._cli_overrides = {}

        if route and route in self.route_overrides:
            for key, val in self.route_overrides[route].items():
                if key in RULE_KEYS and not cli_flags.get(key):
                    setattr(base, key, val)

        for key, was_cli in cli_flags.items():
            if was_cli:
                base._cli_overrides[key] = True
        return base

    def describe_source(self, route: Optional[str] = None) -> str:
        sources = []
        if self._cli_overrides:
            cli_keys = [k for k in RULE_KEYS if self._cli_overrides.get(k)]
            sources.append(f"命令行覆盖({', '.join(cli_keys)})")
        if route and route in self.route_overrides:
            sources.append(f"线路{route}专用规则")
        sources.append("默认规则")
        return " → ".join(sources)

    def to_markdown(self, route: Optional[str] = None) -> str:
        effective = self.rules_for_route(route)
        source = self.describe_source(route)
        lines = [f"  规则来源链: {source}"]

        display = effective
        for key in RULE_KEYS:
            base_val = getattr(self, key)
            eff_val = getattr(display, key)
            cli_override = self._cli_overrides.get(key)
            route_override = (
                route
                and route in self.route_overrides
                and key in self.route_overrides[route]
            )
            origin_label = ""
            if cli_override:
                origin_label = " (CLI覆盖)"
            elif route_override and not cli_override:
                origin_label = " (线路覆盖)"
            lines.append(f"  {key}: {eff_val}{origin_label}")

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
    rules._apply_cli_overrides(overrides)
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
