from pathlib import Path

import pytest

from backend.config import Settings


def test_settings_keep_runtime_files_inside_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """运行环境文件必须始终解析到传入的项目目录。"""
    monkeypatch.setenv("POSTGRES_PASSWORD", "test-password")

    settings = Settings.load(tmp_path)

    assert settings.venv_dir == tmp_path / ".venv"
    assert settings.image_dir == tmp_path / "data" / "images"
    assert settings.cache_environment() == {
        "PIP_CACHE_DIR": str(tmp_path / ".cache" / "pip"),
        "TORCH_HOME": str(tmp_path / ".cache" / "torch"),
        "HF_HOME": str(tmp_path / ".cache" / "huggingface"),
        "HUGGINGFACE_HUB_CACHE": str(tmp_path / ".cache" / "huggingface" / "hub"),
    }


def test_settings_environment_overrides_project_dotenv(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """进程环境变量应优先于项目内 .env，方便部署时安全覆盖。"""
    (tmp_path / ".env").write_text(
        "POSTGRES_PASSWORD=from-dotenv\nPOSTGRES_HOST=dotenv-host\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("POSTGRES_PASSWORD", "from-environment")
    monkeypatch.setenv("POSTGRES_HOST", "environment-host")

    settings = Settings.load(tmp_path)

    assert settings.postgres_password == "from-environment"
    assert settings.postgres_host == "environment-host"


def test_database_url_uses_requested_database_and_preserves_password(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """数据库名覆盖不应通过手工字符串拼接破坏含特殊字符的密码。"""
    monkeypatch.setenv("POSTGRES_PASSWORD", "reserved:/?#[]@")

    url = Settings.load(tmp_path).database_url("alternate_database")

    assert url.drivername == "postgresql+psycopg"
    assert url.host == "127.0.0.1"
    assert url.port == 5432
    assert url.database == "alternate_database"
    assert url.username == "postgres"
    assert url.password == "reserved:/?#[]@"


def test_settings_rejects_missing_database_password(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """缺少密码时应尽早给出不含凭据的中文错误。"""
    monkeypatch.delenv("POSTGRES_PASSWORD", raising=False)

    with pytest.raises(ValueError, match="POSTGRES_PASSWORD"):
        Settings.load(tmp_path)
