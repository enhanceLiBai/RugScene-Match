"""命令行入口的轻量行为测试。"""

from __future__ import annotations

from pathlib import Path

from backend import cli
from backend.config import Settings


def _settings(tmp_path: Path) -> Settings:
    """构造无需读取本机 .env 的最小运行配置。"""
    return Settings(
        project_root=tmp_path,
        postgres_host="127.0.0.1",
        postgres_port=5432,
        postgres_db="carpet_matcher",
        postgres_user="postgres",
        postgres_password="not-a-real-password",
        image_encoder="open_clip",
        clip_model_name="ViT-B-32",
        clip_pretrained="openai",
        model_device="cpu",
        clip_cache_dir=tmp_path / ".cache" / "open_clip",
    )


def test_init_db_does_not_construct_encoder(tmp_path: Path, monkeypatch, capsys) -> None:
    """数据库初始化无需模型，避免不必要地下载权重。"""
    calls: list[Settings] = []
    monkeypatch.setattr(cli.Settings, "load", lambda: _settings(tmp_path))
    monkeypatch.setattr(cli, "create_database_and_schema", lambda settings: calls.append(settings))
    monkeypatch.setattr(cli, "create_encoder", lambda _settings: (_ for _ in ()).throw(AssertionError("不应创建编码器")))

    exit_code = cli.main(["init-db"])

    assert exit_code == 0
    assert calls == [_settings(tmp_path)]
    assert "已初始化" in capsys.readouterr().out


def test_cli_help_lists_all_four_commands_without_loading_settings(capsys, monkeypatch) -> None:
    """帮助属于本地解析行为，不能要求数据库密码或其他外部资源。"""
    monkeypatch.setattr(cli.Settings, "load", lambda: (_ for _ in ()).throw(AssertionError("帮助不应读取配置")))

    parser = cli.create_parser()
    parser.print_help()

    output = capsys.readouterr().out
    assert {"init-db", "import", "search", "serve"}.issubset(output.split())


def test_command_failure_returns_nonzero_and_hides_configuration_details(monkeypatch, capsys) -> None:
    """CLI 失败提示不能把数据库凭据或连接 URL 回显到终端。"""
    monkeypatch.setattr(cli.Settings, "load", lambda: (_ for _ in ()).throw(RuntimeError("postgresql://user:secret@host/db")))

    exit_code = cli.main(["init-db"])

    output = capsys.readouterr().out
    assert exit_code == 1
    assert "命令执行失败" in output
    assert "secret" not in output
