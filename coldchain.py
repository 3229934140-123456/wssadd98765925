#!/usr/bin/env python3
import argparse
import os
import sys

from detector import detect_all_trips
from models import AnomalyLabel
from parser import filter_trips, group_into_trips, load_logs_from_dir
from reporter import build_review_summary, export_report

BANNER = r"""
  ╔══════════════════════════════════════════╗
  ║   冷链运营数据核对工具  v1.0            ║
  ║   Cold Chain Log Checker                ║
  ╚══════════════════════════════════════════╝
"""


def cmd_scan(args):
    dirpath = args.dir
    if not os.path.isdir(dirpath):
        print(f"错误: 目录不存在 -> {dirpath}")
        sys.exit(1)

    print(f"正在扫描日志目录: {dirpath}")
    records = load_logs_from_dir(dirpath)
    print(f"  已加载 {len(records)} 条日志记录")

    if not records:
        print("未找到可解析的日志记录。请检查文件格式(CSV/JSON)。")
        return

    trips = group_into_trips(records)
    print(f"  识别到 {len(trips)} 个行程\n")

    filtered = filter_trips(trips, plate=args.plate, date_str=args.date, route=args.route)
    if not filtered:
        print("没有匹配筛选条件的行程。")
        return

    print("=" * 60)
    print("可解析行程列表")
    print("=" * 60)
    for idx, t in enumerate(filtered, 1):
        print(f"  {idx}. {t}")

    print(f"\n共 {len(filtered)} 个行程，正在检测异常片段...\n")
    segments = detect_all_trips(filtered)

    if not segments:
        print("未检测到异常片段。所有行程数据正常。")
        return

    print("=" * 60)
    print("异常片段清单")
    print("=" * 60)
    for idx, seg in enumerate(segments, 1):
        label_icon = {
            AnomalyLabel.TIRE_PRESSURE_DRAG_COOLING: "⚠",
            AnomalyLabel.PURE_TEMP_FLUCTUATION: "△",
            AnomalyLabel.SENSOR_MALFUNCTION: "✖",
        }.get(seg.label, "?")
        print(f"\n  {idx}. {label_icon} {seg}")
        if seg.detail:
            print(f"       -> {seg.detail}")

    print(f"\n合计 {len(segments)} 个异常片段")

    label_counts = {}
    for seg in segments:
        label_counts[seg.label.value] = label_counts.get(seg.label.value, 0) + 1
    print("分类统计:")
    for label_name, cnt in label_counts.items():
        print(f"  {label_name}: {cnt}个")


def cmd_report(args):
    dirpath = args.dir
    if not os.path.isdir(dirpath):
        print(f"错误: 目录不存在 -> {dirpath}")
        sys.exit(1)

    print(f"正在扫描日志目录: {dirpath}")
    records = load_logs_from_dir(dirpath)
    print(f"  已加载 {len(records)} 条日志记录")

    if not records:
        print("未找到可解析的日志记录。")
        return

    trips = group_into_trips(records)
    segments = detect_all_trips(trips)

    summary = build_review_summary(
        plate=args.plate,
        route=args.route,
        trips=trips,
        segments=segments,
    )

    output_dir = args.output or "."
    filepath = export_report(summary, output_dir=output_dir)
    print(f"\n复盘摘要已导出: {filepath}")
    print("\n--- 报告预览 ---\n")
    print(summary.to_text_report())


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


def main():
    parser = argparse.ArgumentParser(
        prog="coldchain",
        description="冷链运营数据核对工具 - 批量筛查冷藏车胎压与冷机运行日志",
    )
    sub = parser.add_subparsers(dest="command", help="子命令")

    p_scan = sub.add_parser("scan", help="扫描日志，列出行程，检测异常片段")
    p_scan.add_argument("dir", help="日志文件目录路径")
    p_scan.add_argument("--plate", default=None, help="按车牌筛选")
    p_scan.add_argument("--date", default=None, help="按日期筛选 (YYYY-MM-DD)")
    p_scan.add_argument("--route", default=None, help="按线路编号筛选")

    p_report = sub.add_parser("report", help="生成复盘摘要报告")
    p_report.add_argument("dir", help="日志文件目录路径")
    p_report.add_argument("--plate", default=None, help="指定车牌")
    p_report.add_argument("--route", default=None, help="指定线路")
    p_report.add_argument("--output", default=".", help="报告输出目录 (默认当前目录)")

    p_plates = sub.add_parser("list", help="列出目录中所有车牌、线路、日期")
    p_plates.add_argument("dir", help="日志文件目录路径")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(0)

    print(BANNER)

    if args.command == "scan":
        cmd_scan(args)
    elif args.command == "report":
        cmd_report(args)
    elif args.command == "list":
        cmd_plates(args)


if __name__ == "__main__":
    main()
