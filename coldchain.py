#!/usr/bin/env python3
import argparse
import os
import sys

from config import apply_cli_overrides, find_default_config, load_config, save_default_config
from detector import detect_all_trips
from models import AnomalyLabel
from parser import filter_trips, group_into_trips, load_logs_from_dir
from reporter import (
    BatchReviewResult,
    build_batch_review,
    build_review_summary,
    export_anomaly_csv,
    export_report,
)

BANNER = r"""
  ╔══════════════════════════════════════════╗
  ║   冷链运营数据核对工具  v1.2            ║
  ║   Cold Chain Log Checker                ║
  ╚══════════════════════════════════════════╝
"""


def _load_rules(args):
    config_path = args.config or find_default_config()
    if config_path:
        print(f"  使用配置文件: {config_path}")
    rules = load_config(config_path)
    overrides = {
        "tire_low": getattr(args, "tire_low", None),
        "tire_high": getattr(args, "tire_high", None),
        "temp_fluctuation": getattr(args, "temp_fluctuation", None),
        "sensor_jump_pressure": getattr(args, "sensor_jump_pressure", None),
        "sensor_jump_temp": getattr(args, "sensor_jump_temp", None),
        "trip_gap_minutes": getattr(args, "trip_gap_minutes", None),
        "min_segment_minutes": getattr(args, "min_segment_minutes", None),
    }
    return apply_cli_overrides(rules, overrides)


def _add_rule_args(parser):
    parser.add_argument("--config", default=None, help="本地配置文件路径（默认自动查找 coldchain_config.json）")
    parser.add_argument("--tire-low", type=float, default=None, help="胎压下限(bar)，覆盖配置文件")
    parser.add_argument("--tire-high", type=float, default=None, help="胎压上限(bar)，覆盖配置文件")
    parser.add_argument("--temp-fluctuation", type=float, default=None, help="温度波动阈值(°C)")
    parser.add_argument("--sensor-jump-pressure", type=float, default=None, help="胎压传感器跳变阈值(bar)")
    parser.add_argument("--sensor-jump-temp", type=float, default=None, help="温度传感器跳变阈值(°C)")
    parser.add_argument("--trip-gap-minutes", type=float, default=None, help="行程切分间隔(分钟)")
    parser.add_argument("--min-segment-minutes", type=float, default=None, help="最短异常片段时长(分钟)")


def _add_filter_args(parser):
    parser.add_argument("--plate", default=None, help="按车牌筛选")
    parser.add_argument("--date", default=None, help="按日期筛选 (YYYY-MM-DD)")
    parser.add_argument("--date-from", default=None, help="日期范围起始 (YYYY-MM-DD)")
    parser.add_argument("--date-to", default=None, help="日期范围结束 (YYYY-MM-DD)")
    parser.add_argument("--route", default=None, help="按线路编号筛选")


def cmd_scan(args):
    dirpath = args.dir
    if not os.path.isdir(dirpath):
        print(f"错误: 目录不存在 -> {dirpath}")
        sys.exit(1)

    rules = _load_rules(args)
    print(f"\n正在扫描日志目录: {dirpath}")
    records = load_logs_from_dir(dirpath)
    print(f"  已加载 {len(records)} 条日志记录")

    if not records:
        print("未找到可解析的日志记录。请检查文件格式(CSV/JSON)。")
        return

    trips = group_into_trips(records, rules)
    print(f"  识别到 {len(trips)} 个行程\n")

    filtered = filter_trips(
        trips,
        plate=args.plate,
        date_str=args.date,
        date_from=args.date_from,
        date_to=args.date_to,
        route=args.route,
    )
    if not filtered:
        print("没有匹配筛选条件的行程。")
        return

    print("=" * 70)
    print("可解析行程列表")
    print("=" * 70)
    for idx, t in enumerate(filtered, 1):
        print(f"  {idx}. {t}")

    print(f"\n共 {len(filtered)} 个行程，正在检测异常片段...\n")
    segments = detect_all_trips(filtered, rules)

    if not segments:
        print("未检测到异常片段。所有行程数据正常。")
        print("\n本次采用筛查规则:")
        print(rules.to_markdown(args.route))
        return

    print("=" * 70)
    print("异常片段清单")
    print("=" * 70)
    label_icon = {
        AnomalyLabel.TIRE_PRESSURE_DRAG_COOLING: "⚠",
        AnomalyLabel.PURE_TEMP_FLUCTUATION: "△",
        AnomalyLabel.SENSOR_MALFUNCTION: "✖",
    }
    for idx, seg in enumerate(segments, 1):
        icon = label_icon.get(seg.label, "?")
        print(f"\n  {idx}. {icon} {seg}")
        if seg.detail:
            print(f"       -> {seg.detail}")

    print(f"\n合计 {len(segments)} 个异常片段")
    label_counts = {}
    for seg in segments:
        label_counts[seg.label.value] = label_counts.get(seg.label.value, 0) + 1
    print("分类统计:")
    for label_name, cnt in label_counts.items():
        print(f"  {label_name}: {cnt}个")
    print("\n本次采用筛查规则:")
    print(rules.to_markdown(args.route))

    if getattr(args, "export_csv", None):
        csv_path = export_anomaly_csv(segments, args.export_csv, rules=rules, route=args.route)
        print(f"\n异常证据表已导出: {csv_path}")


def cmd_report(args):
    dirpath = args.dir
    if not os.path.isdir(dirpath):
        print(f"错误: 目录不存在 -> {dirpath}")
        sys.exit(1)

    rules = _load_rules(args)
    print(f"\n正在扫描日志目录: {dirpath}")
    records = load_logs_from_dir(dirpath)
    print(f"  已加载 {len(records)} 条日志记录")

    if not records:
        print("未找到可解析的日志记录。")
        return

    trips = group_into_trips(records, rules)
    filtered_trips = filter_trips(
        trips,
        plate=args.plate,
        date_str=args.date,
        date_from=args.date_from,
        date_to=args.date_to,
        route=args.route,
    )
    segments = detect_all_trips(filtered_trips, rules)

    route_val = args.route
    plate_val = args.plate
    if not plate_val and len({t.plate for t in filtered_trips}) == 1:
        plate_val = list({t.plate for t in filtered_trips})[0]
    if not route_val and len({t.route for t in filtered_trips}) == 1:
        route_val = list({t.route for t in filtered_trips})[0]

    summary = build_review_summary(plate_val, route_val, filtered_trips, segments, rules)

    output_dir = args.output or "."
    filepath = export_report(summary, output_dir=output_dir, rules=rules, route=route_val)
    print(f"\n复盘摘要已导出: {filepath}")

    if getattr(args, "export_csv", None):
        csv_path = export_anomaly_csv(segments, args.output or output_dir, rules=rules, route=route_val)
        print(f"异常证据表已导出: {csv_path}")

    print("\n--- 报告预览 ---\n")
    print(summary.to_text_report(rules=rules, route=route_val))


def cmd_batch(args):
    dirpath = args.dir
    if not os.path.isdir(dirpath):
        print(f"错误: 目录不存在 -> {dirpath}")
        sys.exit(1)

    rules = _load_rules(args)
    print(f"\n正在扫描日志目录: {dirpath}")
    records = load_logs_from_dir(dirpath)
    print(f"  已加载 {len(records)} 条日志记录")

    if not records:
        print("未找到可解析的日志记录。")
        return

    trips = group_into_trips(records, rules)
    segments = detect_all_trips(trips, rules)

    prev_trips = None
    prev_segments = None
    prev_date_from = getattr(args, "prev_date_from", None)
    prev_date_to = getattr(args, "prev_date_to", None)
    prev_dir = getattr(args, "prev_dir", None)

    if prev_dir and os.path.isdir(prev_dir):
        print(f"正在加载对比期数据: {prev_dir}")
        prev_records = load_logs_from_dir(prev_dir)
        prev_trips = group_into_trips(prev_records, rules)
        prev_segments = detect_all_trips(prev_trips, rules)
        print(f"  对比期已加载 {len(prev_records)} 条记录")

    output_dir = args.output or "batch_reports"
    result: BatchReviewResult = build_batch_review(
        dirpath=dirpath,
        output_dir=output_dir,
        rules=rules,
        trips=trips,
        segments=segments,
        plate=args.plate,
        date_from=args.date_from,
        date_to=args.date_to,
        route=args.route,
        prev_trips=prev_trips,
        prev_segments=prev_segments,
        prev_date_from=prev_date_from,
        prev_date_to=prev_date_to,
    )

    batch_root = os.path.dirname(result.overview_path)
    print(f"\n批量复盘完成，结果输出到: {batch_root}")
    print(f"  总览TXT: {result.overview_path}")
    print(f"  总览Markdown: {result.markdown_path}")
    print(f"  证据表CSV: {result.evidence_csv_path}")
    print(f"  单车明细: {result.total_vehicles} 辆车")
    for plate, path in sorted(result.per_vehicle_paths.items()):
        print(f"    - {plate}: {path}")
    print(f"\n  覆盖车辆数: {result.total_vehicles}")
    print(f"  异常片段数: {result.total_segments}")

    print("\n--- 总览预览 ---\n")
    with open(result.overview_path, "r", encoding="utf-8") as f:
        print(f.read())


def cmd_plates(args):
    dirpath = args.dir
    if not os.path.isdir(dirpath):
        print(f"错误: 目录不存在 -> {dirpath}")
        sys.exit(1)

    records = load_logs_from_dir(dirpath)
    plates = sorted(set(r.plate for r in records))
    routes = sorted(set(r.route for r in records if r.route))
    dates = sorted(set(r.timestamp.strftime("%Y-%m-%d") for r in records))

    print(f"目录 {dirpath} 中包含:")
    print(f"  车牌: {', '.join(plates) if plates else '无'}")
    print(f"  线路: {', '.join(routes) if routes else '无'}")
    print(f"  日期: {', '.join(dates) if dates else '无'}")
    print(f"  总记录数: {len(records)}")


def cmd_init_config(args):
    target = args.path or "coldchain_config.json"
    if os.path.isfile(target) and not args.force:
        print(f"文件已存在: {target}，使用 --force 覆盖")
        return
    save_default_config(target)
    print(f"已生成默认配置文件: {target}")
    print("可按需修改阈值后使用。")


def main():
    parser = argparse.ArgumentParser(
        prog="coldchain",
        description="冷链运营数据核对工具 - 批量筛查冷藏车胎压与冷机运行日志",
    )
    sub = parser.add_subparsers(dest="command", help="子命令")

    p_scan = sub.add_parser("scan", help="扫描日志，列出行程，检测异常片段")
    p_scan.add_argument("dir", help="日志文件目录路径")
    _add_filter_args(p_scan)
    _add_rule_args(p_scan)
    p_scan.add_argument("--export-csv", default=None, help="同时导出异常证据表到指定目录")

    p_report = sub.add_parser("report", help="生成单车/单线路复盘摘要报告")
    p_report.add_argument("dir", help="日志文件目录路径")
    _add_filter_args(p_report)
    _add_rule_args(p_report)
    p_report.add_argument("--output", default=".", help="报告输出目录 (默认当前目录)")
    p_report.add_argument("--export-csv", action="store_true", help="同时导出异常证据表CSV")

    p_batch = sub.add_parser("batch", help="批量复盘：多车总览+单车明细+Markdown+CSV证据表+月度趋势")
    p_batch.add_argument("dir", help="日志文件目录路径")
    _add_filter_args(p_batch)
    _add_rule_args(p_batch)
    p_batch.add_argument("--output", default="batch_reports", help="输出根目录")
    p_batch.add_argument("--prev-dir", default=None, help="对比期(上月)日志目录，用于趋势对比")
    p_batch.add_argument("--prev-date-from", default=None, help="对比期起始日期 (YYYY-MM-DD)")
    p_batch.add_argument("--prev-date-to", default=None, help="对比期结束日期 (YYYY-MM-DD)")

    p_plates = sub.add_parser("list", help="列出目录中所有车牌、线路、日期")
    p_plates.add_argument("dir", help="日志文件目录路径")

    p_init = sub.add_parser("init-config", help="在当前目录生成默认配置文件模板")
    p_init.add_argument("--path", default=None, help="输出路径，默认 coldchain_config.json")
    p_init.add_argument("--force", action="store_true", help="若存在则覆盖")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(0)

    print(BANNER)

    if args.command == "scan":
        cmd_scan(args)
    elif args.command == "report":
        cmd_report(args)
    elif args.command == "batch":
        cmd_batch(args)
    elif args.command == "list":
        cmd_plates(args)
    elif args.command == "init-config":
        cmd_init_config(args)


if __name__ == "__main__":
    main()
