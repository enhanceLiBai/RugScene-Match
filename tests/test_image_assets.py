"""图片资产校验与安全落盘的行为测试。"""

from dataclasses import replace
import hashlib
from pathlib import Path
import warnings

import pytest
from PIL import Image

import backend.image_assets as image_assets
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


def test_validate_image_rejects_pixel_limit_before_loading(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """超过应用像素上限的图片必须在 Pillow 解码像素前被拒绝。"""
    source = make_png(tmp_path / "large.png")
    monkeypatch.setattr(image_assets, "MAX_IMAGE_PIXELS", 50, raising=False)

    def load_must_not_run(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("load must not run for oversized image")

    monkeypatch.setattr(Image.Image, "load", load_must_not_run)

    with pytest.raises(InvalidImageError, match="large.png"):
        validate_image(source)


def test_validate_image_converts_decompression_bomb_warning_to_invalid_image(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Pillow 解压炸弹警告必须成为安全的业务校验错误。"""
    source = make_png(tmp_path / "warning.png")
    real_open = Image.open

    def open_with_warning(*args: object, **kwargs: object) -> Image.Image:
        warnings.warn("simulated bomb warning", Image.DecompressionBombWarning, stacklevel=2)
        return real_open(*args, **kwargs)

    monkeypatch.setattr(image_assets.Image, "open", open_with_warning)

    with pytest.raises(InvalidImageError, match="warning.png"):
        validate_image(source)


def test_validate_image_converts_decompression_bomb_error_to_invalid_image(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Pillow 解压炸弹错误必须成为安全的业务校验错误。"""
    source = make_png(tmp_path / "error.png")

    def open_with_error(*_args: object, **_kwargs: object) -> Image.Image:
        raise Image.DecompressionBombError("simulated bomb error")

    monkeypatch.setattr(image_assets.Image, "open", open_with_error)

    with pytest.raises(InvalidImageError, match="error.png"):
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


@pytest.mark.parametrize(
    "mutate",
    [
        lambda image: replace(image, sha256="a" * 63),
        lambda image: replace(image, sha256=image.sha256.upper()),
        lambda image: replace(image, sha256="0" * 64),
        lambda image: replace(image, extension=".txt"),
        lambda image: replace(image, extension=".png/../../escaped"),
    ],
)
def test_store_image_rejects_forged_metadata_before_creating_library(
    tmp_path: Path, mutate: object
) -> None:
    """伪造哈希或扩展名时，绝不能创建图库或写入路径范围外文件。"""
    source = make_png(tmp_path / "source.png")
    validated = mutate(validate_image(source))
    image_dir = tmp_path / "library"

    with pytest.raises(InvalidImageError):
        store_image(source, validated, image_dir)

    assert not image_dir.exists()
    assert not (tmp_path / "escaped").exists()


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


@pytest.mark.parametrize("failure_point", ["write", "flush", "fsync"])
def test_store_image_cleans_temporary_file_when_writing_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure_point: str
) -> None:
    """临时文件任一写入阶段失败后，都不能在图库中遗留文件。"""
    source = make_png(tmp_path / "source.png")
    validated = validate_image(source)
    image_dir = tmp_path / "library"
    controlled_temp = image_dir / ".controlled.tmp"
    real_fsync = __import__("os").fsync

    class FailingTemporaryFile:
        def __enter__(self) -> "FailingTemporaryFile":
            image_dir.mkdir(exist_ok=True)
            self.file = controlled_temp.open("wb")
            self.name = str(controlled_temp)
            return self

        def __exit__(self, *_args: object) -> None:
            self.file.close()

        def write(self, data: bytes) -> int:
            if failure_point == "write":
                raise OSError("simulated write failure")
            return self.file.write(data)

        def flush(self) -> None:
            if failure_point == "flush":
                raise OSError("simulated flush failure")
            self.file.flush()

        def fileno(self) -> int:
            return self.file.fileno()

    def fake_fsync(descriptor: int) -> None:
        if failure_point == "fsync":
            raise OSError("simulated fsync failure")
        real_fsync(descriptor)

    monkeypatch.setattr("backend.image_assets.tempfile.NamedTemporaryFile", lambda **_kwargs: FailingTemporaryFile())
    monkeypatch.setattr("backend.image_assets.os.fsync", fake_fsync)

    with pytest.raises(OSError, match=f"simulated {failure_point} failure"):
        store_image(source, validated, image_dir)

    assert list(image_dir.glob(".*.tmp")) == []


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
