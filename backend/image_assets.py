"""图片文件的校验、精确哈希与安全图库落盘。"""

from dataclasses import dataclass
from io import BytesIO
import hashlib
import os
from pathlib import Path, PureWindowsPath
import tempfile
import warnings

from PIL import Image, UnidentifiedImageError


_FORMAT_DETAILS = {
    "JPEG": ("image/jpeg", ".jpg", {".jpg", ".jpeg"}),
    "PNG": ("image/png", ".png", {".png"}),
    "WEBP": ("image/webp", ".webp", {".webp"}),
}
_SUPPORTED_EXTENSIONS = frozenset(extension for _, _, extensions in _FORMAT_DETAILS.values() for extension in extensions)
MAX_IMAGE_PIXELS = 50_000_000


class InvalidImageError(ValueError):
    """表示输入并非可安全导入图库的图片。"""


@dataclass(frozen=True)
class ValidatedImage:
    """已完成内容校验的图片及其安全落盘所需元数据。"""

    sha256: str
    original_name: str
    mime_type: str
    width: int
    height: int
    extension: str
    image: Image.Image
    raw_bytes: bytes


@dataclass(frozen=True)
class StoredImage:
    """原子落盘的结果；created 仅在本调用成功创建目标时为真。"""

    path: Path
    created: bool


def _safe_name(original_name: str) -> str:
    """仅保留文件名，避免把调用方提供的路径回显到异常中。"""
    name = PureWindowsPath(original_name).name
    return name or "未命名图片"


def _validate_extension(name: str) -> str:
    extension = Path(name).suffix.lower()
    if extension not in _SUPPORTED_EXTENSIONS:
        raise InvalidImageError(f"不支持的图片扩展名：{name}")
    return extension


def validate_image(path: Path) -> ValidatedImage:
    """读取路径中的原始字节，并交由统一的字节校验逻辑处理。"""
    safe_name = _safe_name(path.name)
    _validate_extension(safe_name)
    try:
        data = path.read_bytes()
    except OSError as error:
        raise InvalidImageError(f"无法读取图片：{safe_name}") from error
    return validate_image_bytes(data, safe_name)


def validate_image_bytes(data: bytes, original_name: str) -> ValidatedImage:
    """校验内存图片并生成 RGB 图像，哈希始终基于未经转换的原始字节。"""
    safe_name = _safe_name(original_name)
    supplied_extension = _validate_extension(safe_name)
    if not data:
        raise InvalidImageError(f"图片内容为空：{safe_name}")

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(data)) as verified_image:
                image_format = verified_image.format
                details = _FORMAT_DETAILS.get(image_format or "")
                if details is None:
                    raise InvalidImageError(f"不支持的图片内容格式：{safe_name}")
                mime_type, extension, compatible_extensions = details
                if supplied_extension not in compatible_extensions:
                    raise InvalidImageError(f"图片扩展名与内容格式不一致：{safe_name}")
                if verified_image.width <= 0 or verified_image.height <= 0:
                    raise InvalidImageError(f"图片尺寸无效：{safe_name}")
                # 尺寸检查位于完整解码前，防止压缩炸弹耗尽服务内存。
                if verified_image.width * verified_image.height > MAX_IMAGE_PIXELS:
                    raise InvalidImageError(f"图片像素数量超过上限：{safe_name}")
                verified_image.verify()
            with Image.open(BytesIO(data)) as opened_image:
                if opened_image.format != image_format:
                    raise InvalidImageError(f"图片内容格式不稳定：{safe_name}")
                opened_image.load()
                image = opened_image.convert("RGB")
    except (
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
        UnidentifiedImageError,
        OSError,
        ValueError,
        SyntaxError,
    ) as error:
        raise InvalidImageError(f"图片内容无效：{safe_name}") from error

    return ValidatedImage(
        sha256=hashlib.sha256(data).hexdigest(),
        original_name=safe_name,
        mime_type=mime_type,
        width=image.width,
        height=image.height,
        extension=extension,
        image=image,
        raw_bytes=data,
    )


def store_image_bytes(data: bytes, original_name: str, image_dir: Path) -> tuple[ValidatedImage, Path]:
    """校验原始图片字节并复用哈希路径安全落盘，不转换存储格式。"""
    validated = validate_image_bytes(data, original_name)
    return validated, store_image(Path(validated.original_name), validated, image_dir)


def store_image(source: Path, validated: ValidatedImage, image_dir: Path) -> Path:
    """将已验证字节原子写入哈希路径，既有文件永不覆盖。"""
    return store_image_with_ownership(source, validated, image_dir).path


def store_image_with_ownership(source: Path, validated: ValidatedImage, image_dir: Path) -> StoredImage:
    """落盘并返回原子创建归属，供失败补偿安全判断是否可以删除。"""
    del source  # 落盘只使用校验时保留的字节，防止源文件被替换后出现 TOCTOU 不一致。
    expected_sha256 = hashlib.sha256(validated.raw_bytes).hexdigest()
    if validated.sha256 != expected_sha256:
        raise InvalidImageError("图片哈希与已校验内容不一致")
    if validated.extension not in {".jpg", ".png", ".webp"}:
        raise InvalidImageError("图片存储扩展名无效")

    library_root = image_dir.resolve()
    target = (library_root / f"{validated.sha256}{validated.extension}").resolve()
    # 即使未来字段来源变化，也不允许元数据把落盘目标带出图库根目录。
    if not target.is_relative_to(library_root):
        raise InvalidImageError("图片存储路径超出图库目录")
    image_dir.mkdir(parents=True, exist_ok=True)
    if target.exists():
        return StoredImage(target, created=False)

    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", dir=image_dir, prefix=".", suffix=".tmp", delete=False
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
            temporary_file.write(validated.raw_bytes)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        # 硬链接仅在目标不存在时成功，避免并发导入覆盖先完成的同哈希文件。
        try:
            os.link(temporary_path, target)
        except FileExistsError:
            return StoredImage(target, created=False)
        else:
            temporary_path.unlink()
            temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)

    return StoredImage(target, created=True)
