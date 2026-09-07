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
    workbook = _read_xml(archive, workbook_path)
    workbook_relationships = _relationship_map(_read_xml(archive, "xl/_rels/workbook.xml.rels"))

    sheet_relationship_id = _find_carpet_sheet_relationship_id(workbook)
    worksheet_path = _resolve_relationship_path(workbook_path, workbook_relationships[sheet_relationship_id], entries)
    worksheet = _read_xml(archive, worksheet_path)
    product_ids = _product_ids_by_row(worksheet, _shared_strings(archive, entries))

    drawing_relationship_id = _find_drawing_relationship_id(worksheet)
    worksheet_relationships_path = _rels_path(worksheet_path)
    drawing_relationships = _relationship_map(_read_xml(archive, worksheet_relationships_path))
    drawing_path = _resolve_relationship_path(
        worksheet_path, drawing_relationships[drawing_relationship_id], entries
    )
    drawing = _read_xml(archive, drawing_path)
    drawing_relationships = _relationship_map(_read_xml(archive, _rels_path(drawing_path)))

    for row, column, embed_id in _image_anchors(drawing):
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


def _read_xml(archive: ZipFile, path: str) -> ElementTree.Element:
    try:
        return ElementTree.fromstring(archive.read(path))
    except (KeyError, ElementTree.ParseError) as error:
        raise WorkbookStructureError("工作簿结构错误") from error


def _relationship_map(root: ElementTree.Element) -> dict[str, str]:
    relationships: dict[str, str] = {}
    for element in root.iter():
        if _local_name(element.tag) != "Relationship":
            continue
        identifier = element.get("Id")
        target = element.get("Target")
        if not identifier or not target:
            raise WorkbookStructureError("工作簿结构错误")
        relationships[identifier] = target
    return relationships


def _find_carpet_sheet_relationship_id(workbook: ElementTree.Element) -> str:
    for element in workbook.iter():
        if _local_name(element.tag) != "sheet" or element.get("name") != "地毯图片":
            continue
        relationship_id = element.get(f"{OFFICE_RELATIONSHIP}id")
        if relationship_id:
            return relationship_id
    raise WorkbookStructureError("找不到工作表：地毯图片")


def _find_drawing_relationship_id(worksheet: ElementTree.Element) -> str:
    for element in worksheet.iter():
        if _local_name(element.tag) == "drawing":
            relationship_id = element.get(f"{OFFICE_RELATIONSHIP}id")
            if relationship_id:
                return relationship_id
    raise WorkbookStructureError("工作簿结构错误")


def _shared_strings(archive: ZipFile, entries: set[str]) -> list[str]:
    path = "xl/sharedStrings.xml"
    if path not in entries:
        return []
    root = _read_xml(archive, path)
    return ["".join(element.itertext()) for element in root.iter() if _local_name(element.tag) == "si"]


def _product_ids_by_row(worksheet: ElementTree.Element, shared_strings: list[str]) -> dict[int, str]:
    product_ids: dict[int, str] = {}
    for cell in worksheet.iter():
        if _local_name(cell.tag) != "c":
            continue
        match = CELL_REFERENCE.match(cell.get("r", ""))
        if match is None or match.group(1).upper() != "F":
            continue
        value = _cell_value(cell, shared_strings)
        if value:
            product_ids[int(match.group(2))] = value
    return product_ids


def _cell_value(cell: ElementTree.Element, shared_strings: list[str]) -> str:
    cell_type = cell.get("t")
    if cell_type == "inlineStr":
        inline = _first_descendant(cell, "is")
        return "".join(inline.itertext()).strip() if inline is not None else ""
    value = _first_descendant(cell, "v")
    if value is None or value.text is None:
        return ""
    text = value.text.strip()
    if cell_type != "s":
        return text
    try:
        return shared_strings[int(text)].strip()
    except (IndexError, ValueError):
        raise WorkbookStructureError("工作簿结构错误") from None


def _image_anchors(drawing: ElementTree.Element) -> Iterator[tuple[int, int, str]]:
    for anchor in drawing.iter():
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
