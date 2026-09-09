"""以流式方式读取腾讯文档 XLSX 中与商品关联的原始图片。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath
import posixpath
import re
from typing import Iterator, Literal
from xml.etree import ElementTree
from zipfile import BadZipFile, ZipFile


OFFICE_RELATIONSHIP = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
CELL_REFERENCE = re.compile(r"^([A-Za-z]+)([1-9][0-9]*)$")


class WorkbookStructureError(ValueError):
    """工作簿缺少解析所需的 XML、关系或图片时抛出。"""


@dataclass(frozen=True)
class WorkbookImage:
    """工作簿内一张与商品 ID 对应的原始图片。"""

    product_id: str
    role: Literal["product_main", "buyer_sofa"]
    source_column: Literal["K", "L", "M", "N"]
    filename: str
    data: bytes


def iter_product_images(path: Path) -> Iterator[WorkbookImage]:
    """按锚点顺序产生“地毯图片”工作表中 K-N 列关联的图片。"""
    try:
        with ZipFile(path) as archive:
            yield from _iter_archive_images(archive)
    except WorkbookStructureError:
        raise
    except (BadZipFile, ElementTree.ParseError, KeyError, OSError, ValueError):
        raise WorkbookStructureError("工作簿结构错误") from None


def _iter_archive_images(archive: ZipFile) -> Iterator[WorkbookImage]:
    entries = set(archive.namelist())
    workbook_path = "xl/workbook.xml"
    workbook_relationships = _relationship_map(archive, "xl/_rels/workbook.xml.rels")

    sheet_relationship_id = _find_carpet_sheet_relationship_id(archive, workbook_path)
    worksheet_path = _resolve_relationship_path(workbook_path, workbook_relationships[sheet_relationship_id], entries)
    raw_product_ids, drawing_relationship_id = _worksheet_details(archive, worksheet_path)
    product_ids = _resolve_product_ids(archive, entries, raw_product_ids)

    worksheet_relationships_path = _rels_path(worksheet_path)
    worksheet_relationships = _relationship_map(archive, worksheet_relationships_path) if worksheet_relationships_path in entries else {}
    if drawing_relationship_id is None and "xl/cellimages.xml" in entries:
        yield from _iter_cellimages(archive, worksheet_path, product_ids, entries)
        return
    drawing_path = _resolve_relationship_path(
        worksheet_path, worksheet_relationships[drawing_relationship_id], entries
    )
    drawing_relationships = _relationship_map(archive, _rels_path(drawing_path))

    for row, column, embed_id in _image_anchors(archive, drawing_path):
        column_info = _image_column(column)
        if column_info is None:
            continue
        product_id = product_ids.get(row + 1)
        if not product_id:
            continue
        media_path = _resolve_relationship_path(drawing_path, drawing_relationships[embed_id], entries)
        # 仅在即将产出时读取单张图片，避免解压整个工作簿的媒体文件。
        data = archive.read(media_path)
        role, source_column = column_info
        yield WorkbookImage(
            product_id=product_id,
            role=role,
            source_column=source_column,
            filename=PurePosixPath(media_path).name,
            data=data,
        )


def _iter_cellimages(
    archive: ZipFile, worksheet_path: str, product_ids: dict[int, str], entries: set[str]
) -> Iterator[WorkbookImage]:
    """解析腾讯导出的 DISPIMG 单元格图片映射。"""
    formulas: list[tuple[int, int, str]] = []
    for cell in _iterparse(archive, worksheet_path):
        if _local_name(cell.tag) != "c":
            continue
        match = CELL_REFERENCE.match(cell.get("r", ""))
        formula = _first_descendant(cell, "f")
        if match is None or formula is None:
            cell.clear()
            continue
        image_key = re.search(r'DISPIMG\(\s*"([^"]+)"', formula.text or "", re.I)
        if image_key is None:
            cell.clear()
            continue
        column = _column_number(match.group(1))
        if _image_column(column) is not None:
            formulas.append((int(match.group(2)), column, image_key.group(1)))
        cell.clear()
    rels_path = "xl/_rels/cellimages.xml.rels"
    image_rels = _relationship_map(archive, rels_path)
    names: dict[str, str] = {}
    for item in _iterparse(archive, "xl/cellimages.xml"):
        if _local_name(item.tag) != "cellImage":
            continue
        name = _first_descendant(item, "cNvPr")
        blip = _first_descendant(item, "blip")
        if name is not None and blip is not None:
            rid = blip.get(f"{OFFICE_RELATIONSHIP}embed")
            if rid in image_rels:
                names[name.get("name", "")] = image_rels[rid]
        item.clear()
    for row, column, key in formulas:
        info = _image_column(column)
        target = names.get(key)
        product_id = product_ids.get(row)
        if info is None or target is None or product_id is None:
            continue
        media_path = _resolve_relationship_path("xl/cellimages.xml", target, entries)
        role, source_column = info
        yield WorkbookImage(product_id, role, source_column, PurePosixPath(media_path).name, archive.read(media_path))


def _column_number(value: str) -> int:
    number = 0
    for char in value.upper():
        number = number * 26 + ord(char) - 64
    return number - 1


def _iterparse(archive: ZipFile, path: str) -> Iterator[ElementTree.Element]:
    """流式读取 XML，并将元素清理时机交给了解父子依赖的调用方。"""
    try:
        with archive.open(path) as stream:
            for _, element in ElementTree.iterparse(stream, events=("end",)):
                yield element
    except (KeyError, ElementTree.ParseError) as error:
        raise WorkbookStructureError("工作簿结构错误") from error


def _relationship_map(archive: ZipFile, path: str) -> dict[str, str]:
    relationships: dict[str, str] = {}
    for element in _iterparse(archive, path):
        if _local_name(element.tag) != "Relationship":
            continue
        identifier = element.get("Id")
        target = element.get("Target")
        if not identifier or not target:
            raise WorkbookStructureError("工作簿结构错误")
        relationships[identifier] = target
        element.clear()
    return relationships


def _find_carpet_sheet_relationship_id(archive: ZipFile, path: str) -> str:
    for element in _iterparse(archive, path):
        if _local_name(element.tag) != "sheet" or element.get("name") != "地毯图片":
            element.clear()
            continue
        relationship_id = element.get(f"{OFFICE_RELATIONSHIP}id")
        element.clear()
        if relationship_id:
            return relationship_id
    raise WorkbookStructureError("找不到工作表：地毯图片")


def _shared_strings(archive: ZipFile, entries: set[str], wanted_indexes: set[int]) -> dict[int, str]:
    """仅读取 F 列实际引用的共享字符串，避免保存完整字符串表。"""
    if not wanted_indexes:
        return {}
    path = "xl/sharedStrings.xml"
    if path not in entries:
        raise WorkbookStructureError("工作簿结构错误")
    strings: dict[int, str] = {}
    index = 0
    for element in _iterparse(archive, path):
        if _local_name(element.tag) != "si":
            continue
        if index in wanted_indexes:
            strings[index] = "".join(element.itertext()).strip()
        element.clear()
        if len(strings) == len(wanted_indexes):
            return strings
        index += 1
    return strings


def _worksheet_details(archive: ZipFile, path: str) -> tuple[dict[int, str | int], str | None]:
    product_ids: dict[int, str | int] = {}
    drawing_relationship_id: str | None = None
    for element in _iterparse(archive, path):
        name = _local_name(element.tag)
        if name == "c":
            _record_product_id(element, product_ids)
            element.clear()
            continue
        if name == "drawing":
            drawing_relationship_id = element.get(f"{OFFICE_RELATIONSHIP}id")
            element.clear()
            continue
        if name == "row":
            element.clear()
    if drawing_relationship_id is None and "xl/cellimages.xml" not in set(archive.namelist()):
        raise WorkbookStructureError("工作簿结构错误")
    return product_ids, drawing_relationship_id


def _record_product_id(
    cell: ElementTree.Element, product_ids: dict[int, str | int]
) -> None:
    match = CELL_REFERENCE.match(cell.get("r", ""))
    if match is None or match.group(1).upper() != "F":
        return
    if cell.get("t") == "s":
        value = _shared_string_index(cell)
    else:
        value = _cell_value(cell)
    if value is not None and value != "":
        product_ids[int(match.group(2))] = value


def _resolve_product_ids(
    archive: ZipFile, entries: set[str], raw_product_ids: dict[int, str | int]
) -> dict[int, str]:
    shared_indexes = {value for value in raw_product_ids.values() if isinstance(value, int)}
    shared_strings = _shared_strings(archive, entries, shared_indexes)
    product_ids: dict[int, str] = {}
    for row, value in raw_product_ids.items():
        if isinstance(value, int):
            try:
                product_ids[row] = shared_strings[value]
            except KeyError:
                raise WorkbookStructureError("工作簿结构错误") from None
        else:
            product_ids[row] = value
    return product_ids


def _cell_value(cell: ElementTree.Element) -> str:
    cell_type = cell.get("t")
    if cell_type == "inlineStr":
        inline = _first_descendant(cell, "is")
        return "".join(inline.itertext()).strip() if inline is not None else ""
    value = _first_descendant(cell, "v")
    if value is None or value.text is None:
        return ""
    return value.text.strip()


def _shared_string_index(cell: ElementTree.Element) -> int | None:
    value = _first_descendant(cell, "v")
    if value is None or value.text is None:
        return None
    try:
        return int(value.text.strip())
    except ValueError:
        raise WorkbookStructureError("工作簿结构错误") from None


def _image_anchors(archive: ZipFile, path: str) -> Iterator[tuple[int, int, str]]:
    for anchor in _iterparse(archive, path):
        if _local_name(anchor.tag) != "oneCellAnchor":
            continue
        origin = _first_descendant(anchor, "from")
        blip = _first_descendant(anchor, "blip")
        if origin is None or blip is None:
            raise WorkbookStructureError("工作簿结构错误")
        column = _integer_child(origin, "col")
        row = _integer_child(origin, "row")
        embed_id = blip.get(f"{OFFICE_RELATIONSHIP}embed")
        if embed_id is None:
            raise WorkbookStructureError("工作簿结构错误")
        anchor.clear()
        yield row, column, embed_id


def _image_column(
    column: int,
) -> tuple[Literal["product_main", "buyer_sofa"], Literal["K", "L", "M", "N"]] | None:
    columns = {
        10: ("product_main", "K"),
        11: ("buyer_sofa", "L"),
        12: ("buyer_sofa", "M"),
        13: ("buyer_sofa", "N"),
    }
    return columns.get(column)


def _integer_child(element: ElementTree.Element, name: str) -> int:
    child = _first_descendant(element, name)
    if child is None or child.text is None:
        raise WorkbookStructureError("工作簿结构错误")
    try:
        return int(child.text)
    except ValueError:
        raise WorkbookStructureError("工作簿结构错误") from None


def _resolve_relationship_path(source_path: str, target: str, entries: set[str]) -> str:
    if target.startswith(("/", "\\")):
        raise WorkbookStructureError("工作簿结构错误")
    path = posixpath.normpath(posixpath.join(posixpath.dirname(source_path), target))
    if path == "." or path.startswith("../") or path not in entries:
        raise WorkbookStructureError("工作簿结构错误")
    return path


def _rels_path(source_path: str) -> str:
    path = PurePosixPath(source_path)
    return str(path.parent / "_rels" / f"{path.name}.rels")


def _first_descendant(element: ElementTree.Element, name: str) -> ElementTree.Element | None:
    return next((item for item in element.iter() if _local_name(item.tag) == name), None)


def _local_name(tag: str) -> str:
    return tag.rsplit("}", maxsplit=1)[-1]
