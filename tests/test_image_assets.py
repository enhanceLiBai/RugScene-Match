"""图片资产校验与安全落盘的行为测试。"""

import hashlib
from pathlib import Path

import pytest
from PIL import Image

from backend.image_assets import InvalidImageError, store_image, validate_image, validate_image_bytes


def make_png(path: Path, color: str = "red") -> Path:
    """创建真实 PNG 文件，供各行为测试使用。"""
    Image.new("RGB", (12, 8), color).save(path)
    return path


def test_validate_image_returns_dimensions_rgb_and_byte_hash(tmp_path: Path) -> None:
    """校验应转换 RGBA，同时保留原始文件字节的精确哈希。"""
    source = tmp_path / "样图.png"
    Image.new("RGBA", (12, 8), (10, 20, 30, 120)).save(source)

    result = validate_image(source)

    assert result.width == 12
    assert result.height == 8
    assert result.image.mode == "RGB"
    assert result.sha256 == hashlib.sha256(source.read_bytes()).hexdigest()
    assert result.original_name == "样图.png"
    assert result.mime_type == "image/png"
    assert result.extension == ".png"


def test_validate_image_bytes_reuses_content_validation_and_canonicalizes_jpeg(tmp_path: Path) -> None:
    """字节入口也必须依据内容而非伪装文件名推导 JPEG 类型。"""
    source = tmp_path / "fixture.jpg"
    Image.new("RGB", (5, 3), "blue").save(source, format="JPEG")
    data = source.read_bytes()

    result = validate_image_bytes(data, "伪装成.png.JPEG")

    assert result.sha256 == hashlib.sha256(data).hexdigest()
    assert result.original_name == "伪装成.png.JPEG"
    assert result.mime_type == "image/jpeg"
    assert result.extension == ".jpg"
    assert result.image.mode == "RGB"


def test_validate_image_accepts_uppercase_supported_extension(tmp_path: Path) -> None:
    """扩展名校验必须大小写无关。"""
    source = make_png(tmp_path / "PHOTO.PNG")

    result = validate_image(source)

    assert result.extension == ".png"


def test_validate_image_rejects_unsupported_extension_before_decoding(tmp_path: Path) -> None:
    """即使内容是图片，非允许扩展名也不能进入图库。"""
    source = make_png(tmp_path / "not-an-image.gif")

    with pytest.raises(InvalidImageError, match="not-an-image.gif"):
        validate_image(source)


@pytest.mark.parametrize(
    ("data", "name"),
    [(b"", "empty.png"), (b"not-an-image", "broken.jpg")],
)
def test_validate_image_bytes_rejects_empty_or_corrupt_data_without_leaking_bytes(data: bytes, name: str) -> None:
    """空或损坏数据应报安全文件名，异常文本不能回显原始字节。"""
    with pytest.raises(InvalidImageError) as error:
        validate_image_bytes(data, name)

    assert name in str(error.value)
    assert repr(data) not in str(error.value)


def test_validate_image_rejects_content_format_that_disagrees_with_filename(tmp_path: Path) -> None:
    """文件扩展名和解码格式不一致时，不能以文件名伪装格式入库。"""
    source = tmp_path / "misleading.jpg"
    Image.new("RGB", (12, 8), "red").save(source, format="PNG")

    with pytest.raises(InvalidImageError, match="misleading.jpg"):
        validate_image(source)


def test_store_image_uses_hash_name_and_does_not_overwrite(tmp_path: Path) -> None:
    """首次存储写入已校验字节，重复调用保持幂等。"""
    source = make_png(tmp_path / "source.png")
    validated = validate_image(source)

    first = store_image(source, validated, tmp_path / "library")
    second = store_image(source, validated, tmp_path / "library")

    assert first == second
    assert first.name == f"{validated.sha256}.png"
    assert first.read_bytes() == source.read_bytes()


def test_store_image_keeps_existing_hash_target_unchanged(tmp_path: Path) -> None:
    """已有哈希目标被占用时必须不覆盖，避免破坏已入库文件。"""
    source = make_png(tmp_path / "source.png")
    validated = validate_image(source)
    image_dir = tmp_path / "library"
    image_dir.mkdir()
    target = image_dir / f"{validated.sha256}.png"
    target.write_bytes(b"existing-library-content")

    result = store_image(source, validated, image_dir)

    assert result == target
    assert target.read_bytes() == b"existing-library-content"


def test_store_image_does_not_overwrite_target_created_during_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """目标在提交瞬间由其他进程创建时，也必须保留对方已有内容。"""
    source = make_png(tmp_path / "source.png")
    validated = validate_image(source)
    image_dir = tmp_path / "library"
    target = image_dir / f"{validated.sha256}.png"
    def competitor_wins(_temporary: object, destination: object, *_args: object, **_kwargs: object) -> None:
        Path(destination).write_bytes(b"concurrent-library-content")
        raise FileExistsError

    monkeypatch.setattr("backend.image_assets.os.link", competitor_wins)

    result = store_image(source, validated, image_dir)

    assert result == target
    assert target.read_bytes() == b"concurrent-library-content"
    assert list(image_dir.glob(".*.tmp")) == []


def test_store_image_uses_validated_bytes_after_source_changes(tmp_path: Path) -> None:
    """源文件校验后被替换时，落盘仍必须对应已校验的哈希字节。"""
    source = make_png(tmp_path / "source.png", color="red")
    validated = validate_image(source)
    original = source.read_bytes()
    make_png(source, color="blue")

    stored = store_image(source, validated, tmp_path / "library")

    assert stored.read_bytes() == original


def test_store_image_cleans_temporary_files_when_link_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """原子替换失败时，图库目录中不能遗留临时文件。"""
    source = make_png(tmp_path / "source.png")
    validated = validate_image(source)
    image_dir = tmp_path / "library"

    def fail_link(*_args: object, **_kwargs: object) -> None:
        raise OSError("simulated link failure")

    monkeypatch.setattr("backend.image_assets.os.link", fail_link)

    with pytest.raises(OSError, match="simulated link failure"):
        store_image(source, validated, image_dir)

    assert list(image_dir.glob(".*.tmp")) == []
