import json
import os
from dataclasses import asdict, dataclass, field
from typing import Optional


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

    def to_markdown(self) -> str:
        lines = [
            f"  胎压下限: {self.tire_low} bar",
            f"  胎压上限: {self.tire_high} bar",
            f"  温度波动阈值: ±{self.temp_fluctuation}°C",
            f"  胎压传感器跳变阈值: {self.sensor_jump_pressure} bar",
            f"  温度传感器跳变阈值: {self.sensor_jump_temp}°C",
            f"  行程切分间隔: {self.trip_gap_minutes} min",
            f"  最短异常片段时长: {self.min_segment_minutes} min",
            f"  启用单点异常保留: {'是' if self.enable_single_point_anomaly else '否'}",
        ]
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
    data = asdict(ScreenRules())
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return path
