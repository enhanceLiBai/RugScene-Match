"""合并同商品同款式的明确营销后缀目录，默认仅输出预览。"""

from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path


# 仅处理业务明确确认的营销后缀；材质、颜色、花型等真实款式词绝不自动剥离。
MARKETING_SUFFIXES = (
    "可享国补",
    "国补",
    "预售15天",
    "百搭不出错",
    "轻奢风推荐",
    "意式轻奢推荐",
    "中古大宅推荐",
    "北欧风推荐",
    "中古多巴胺推荐",
    "暖调中古推荐",
    "原木中古推荐",
    "中古推荐",
)
PARENTHESES = "（()）"
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}


def canonical_style(style: str) -> str:
    """去除末尾一个或多个已确认的营销括号后缀。"""
    normalized = style.strip()
    while True:
        matched = re.search(r"[（(]([^（）()]*)[）)]\s*$", normalized)
        if not matched or matched.group(1).strip() not in MARKETING_SUFFIXES:
            return normalized
        normalized = normalized[:matched.start()].rstrip()


def parse_directory(name: str) -> tuple[str, str]:
    product_id, separator, style = name.partition("_")
    if not separator or not product_id or not style.strip():
        raise ValueError("目录必须为商品ID_款式")
    return product_id, style.strip()


def available_target(target: Path) -> Path:
    if not target.exists():
        return target
    index = 2
    while True:
        candidate = target.with_name(f"{target.stem}_{index}{target.suffix}")
        if not candidate.exists():
            return candidate
        index += 1


def collect_moves(root: Path) -> list[tuple[Path, Path]]:
    moves: list[tuple[Path, Path]] = []
    for directory in sorted((item for item in root.iterdir() if item.is_dir()), key=lambda item: item.name):
        product_id, style = parse_directory(directory.name)
        standard_style = canonical_style(style)
        if standard_style == style:
            continue
        target_directory = root / f"{product_id}_{standard_style}"
        if not target_directory.is_dir():
            # 没有基础款目录时，不猜测是否应该新建并合并，保留供人工核对。
            continue
        for item in directory.iterdir():
            if item.is_file() and item.suffix.lower() in IMAGE_SUFFIXES:
                moves.append((item, target_directory / item.name))
    return moves


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="合并已确认营销后缀目录；默认只预览")
    parser.add_argument("root", type=Path)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--report", type=Path, default=Path("data/style-merge-report.jsonl"))
    args = parser.parse_args(argv)
    root = args.root.resolve()
    if not root.is_dir():
        parser.error("根目录必须是可访问文件夹")
    moves = collect_moves(root)
    if not args.execute:
        print(json.dumps({"planned_moves": len(moves)}, ensure_ascii=False))
        for source, target in moves:
            print(json.dumps({"source": str(source), "target": str(target)}, ensure_ascii=False))
        return 0

    args.report.parent.mkdir(parents=True, exist_ok=True)
    with args.report.open("a", encoding="utf-8") as report:
        for source, target in moves:
            resolved_target = available_target(target)
            os.replace(source, resolved_target)
            report.write(json.dumps({"source": str(source), "target": str(resolved_target)}, ensure_ascii=False) + "\n")
            report.flush()
            print(json.dumps({"moved": source.name, "to": str(resolved_target.parent.name)}, ensure_ascii=False))
        for directory in sorted((item for item in root.iterdir() if item.is_dir()), key=lambda item: item.name):
            _, style = parse_directory(directory.name)
            remaining = [item for item in directory.iterdir() if item.name.casefold() != "thumbs.db"]
            if canonical_style(style) != style and not remaining:
                thumbs = directory / "Thumbs.db"
                if thumbs.is_file():
                    thumbs.unlink()
                directory.rmdir()
                print(json.dumps({"removed_empty_directory": directory.name}, ensure_ascii=False))
    print(json.dumps({"moved": len(moves)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
