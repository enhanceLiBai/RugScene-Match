"""图片建库与检索命令行入口。"""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path
from typing import Callable

from backend.config import Settings
from backend.db import create_database_and_schema, create_session_factory, dispose_session_factory
from backend.encoders.factory import create_encoder
from backend.repository import ImageRepository
from backend.services import ImportStatus, LibraryService


def build_library_service(settings: Settings) -> tuple[LibraryService, Callable[[], None]]:
    """构造短命令所需对象，并返回显式释放数据库连接池的回调。"""
    factory = create_session_factory(settings)
    session = factory()
    service = LibraryService(
        repository=ImageRepository(session),
        encoder=create_encoder(settings),
        image_dir=settings.image_dir,
        project_root=settings.project_root,
    )

    def close() -> None:
        session.close()
        dispose_session_factory(factory)

    return service, close


def create_parser() -> argparse.ArgumentParser:
    """创建纯 argparse 解析器，帮助路径不读取配置或连接外部资源。"""
    parser = argparse.ArgumentParser(description="本地图像向量建库与相似检索工具")
    commands = parser.add_subparsers(dest="command", required=True, title="子命令")
    commands.add_parser("init-db", help="创建数据库、vector 扩展和表结构")
    import_parser = commands.add_parser("import", help="导入图片文件或目录")
    import_parser.add_argument("path", type=Path, help="图片文件或包含图片的目录")
    search_parser = commands.add_parser("search", help="按查询图片检索相似结果")
    search_parser.add_argument("path", type=Path, help="查询图片文件")
    search_parser.add_argument("--top-k", type=int, default=5, help="返回数量，范围为 1 到 50（默认：5）")
    serve_parser = commands.add_parser("serve", help="启动 HTTP 服务")
    serve_parser.add_argument("--host", default="0.0.0.0", help="监听地址（默认：0.0.0.0，允许局域网访问）")
    serve_parser.add_argument("--port", type=int, default=8000, help="监听端口（默认：8000）")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """执行指定子命令，发生错误时只输出不含敏感信息的中文提示。"""
    args = create_parser().parse_args(argv)
    try:
        if args.command == "init-db":
            create_database_and_schema(Settings.load())
            print("数据库和表结构已初始化。")
            return 0
        if args.command == "import":
            return _run_import(args.path)
        if args.command == "search":
            return _run_search(args.path, args.top_k)
        if args.command == "serve":
            return _run_server(args.host, args.port)
    except Exception:
        print("命令执行失败，请检查配置、数据库连接和输入文件。")
        return 1
    return 1


def _run_import(path: Path) -> int:
    """导入后逐条输出状态，再给出便于脚本使用的汇总。"""
    service, close = build_library_service(Settings.load())
    try:
        results = service.import_path(path)
    finally:
        close()
    for result in results:
        print(f"{result.status.value}: {result.path} - {result.message}")
    failed = sum(result.status is ImportStatus.FAILED for result in results)
    imported = sum(result.status is ImportStatus.IMPORTED for result in results)
    duplicates = sum(result.status is ImportStatus.DUPLICATE for result in results)
    added = sum(result.status is ImportStatus.EMBEDDING_ADDED for result in results)
    print(f"汇总：导入 {imported}，重复 {duplicates}，补向量 {added}，失败 {failed}。")
    return 1 if failed else 0


def _run_search(path: Path, top_k: int) -> int:
    """打印稳定的检索名次，空结果也是成功完成的查询。"""
    service, close = build_library_service(Settings.load())
    try:
        results = service.search(path, top_k)
    finally:
        close()
    if not results:
        print("当前模型没有可用的相似图片结果。")
        return 0
    for item in results:
        print(f"{item.rank}. 图片 ID {item.image_id}，{item.original_name}，{item.stored_path}，相似度 {item.similarity_percent:.2f}%")
    return 0


def _run_server(host: str, port: int) -> int:
    """延迟委托给 Uvicorn，避免帮助和其他命令导入未来的 API 路由。"""
    import uvicorn

    uvicorn.run("backend.api:app", host=host, port=port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
