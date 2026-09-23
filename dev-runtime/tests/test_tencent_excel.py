"""腾讯文档 XLSX 图片锚点解析的行为测试。"""

from __future__ import annotations

from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

from backend.tencent_excel import WorkbookStructureError, iter_product_images


PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def write_tencent_workbook(
    path: Path,
    *,
    sheet_name: str = "地毯图片",
    product_cell: str = '<c r="F2" t="n"><v>1001</v></c>',
    include_shared_strings: bool = False,
) -> None:
    """写入一个具备腾讯文档常见图片关系结构的最小 XLSX。"""
    anchors = "".join(
        f"""
        <xdr:oneCellAnchor>
          <xdr:from><xdr:col>{column}</xdr:col><xdr:row>1</xdr:row></xdr:from>
          <xdr:ext cx="1" cy="1"/><xdr:pic><xdr:blipFill>
            <a:blip r:embed="rId{index}"/>
          </xdr:blipFill></xdr:pic>
        </xdr:oneCellAnchor>
        """
        for index, column in enumerate(range(9, 15), start=1)
    )
    workbook_xml = f"""
    <workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
      xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
      <sheets><sheet name="{sheet_name}" sheetId="1" r:id="rId1"/></sheets>
    </workbook>
    """
    worksheet_xml = f"""
    <worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
      xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
      <sheetData><row r="2">{product_cell}</row></sheetData>
      <drawing r:id="rId1"/>
    </worksheet>
    """
    drawing_xml = f"""
    <xdr:wsDr xmlns:xdr="http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing"
      xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"
      xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
      {anchors}
    </xdr:wsDr>
    """
    drawing_rels = "".join(
        f'<Relationship Id="rId{index}" Type="image" Target="../media/image{index}.png"/>'
        for index in range(1, 7)
    )
    with ZipFile(path, "w", ZIP_DEFLATED) as archive:
        archive.writestr("xl/workbook.xml", workbook_xml)
        archive.writestr(
            "xl/_rels/workbook.xml.rels",
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="worksheet" Target="worksheets/sheet1.xml"/>'
            "</Relationships>",
        )
        archive.writestr("xl/worksheets/sheet1.xml", worksheet_xml)
        archive.writestr(
            "xl/worksheets/_rels/sheet1.xml.rels",
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="drawing" Target="../drawings/drawing1.xml"/>'
            "</Relationships>",
        )
        archive.writestr("xl/drawings/drawing1.xml", drawing_xml)
        archive.writestr(
            "xl/drawings/_rels/drawing1.xml.rels",
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            f"{drawing_rels}</Relationships>",
        )
        if include_shared_strings:
            archive.writestr(
                "xl/sharedStrings.xml",
                '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                "<si><t>SKU-共享</t></si></sst>",
            )
        for index in range(1, 7):
            archive.writestr(f"xl/media/image{index}.png", PNG_SIGNATURE + bytes([index]))


def test_iter_product_images_returns_only_k_to_n_with_shared_product_id(tmp_path: Path) -> None:
    """J/O 图片必须忽略，K-N 四图应绑定 F 列同一商品。"""
    workbook = tmp_path / "tencent.xlsx"
    write_tencent_workbook(workbook)

    images = list(iter_product_images(workbook))

    assert [(image.product_id, image.role, image.source_column, image.filename) for image in images] == [
        ("1001", "product_main", "K", "image2.png"),
        ("1001", "buyer_sofa", "L", "image3.png"),
        ("1001", "buyer_sofa", "M", "image4.png"),
        ("1001", "buyer_sofa", "N", "image5.png"),
    ]
    assert all(image.data.startswith(PNG_SIGNATURE) for image in images)


@pytest.mark.parametrize(
    ("product_cell", "include_shared_strings", "expected_product_id"),
    [
        ('<c r="F2" t="n"><v>1001</v></c>', False, "1001"),
        ('<c r="F2" t="s"><v>0</v></c>', True, "SKU-共享"),
        ('<c r="F2" t="inlineStr"><is><t>SKU-内联</t></is></c>', False, "SKU-内联"),
    ],
)
def test_iter_product_images_reads_supported_product_id_cell_types(
    tmp_path: Path, product_cell: str, include_shared_strings: bool, expected_product_id: str
) -> None:
    """F 列的普通数值、共享字符串和内联字符串都应作为商品 ID。"""
    workbook = tmp_path / "cell-types.xlsx"
    write_tencent_workbook(
        workbook, product_cell=product_cell, include_shared_strings=include_shared_strings
    )

    images = list(iter_product_images(workbook))

    assert [image.product_id for image in images] == [expected_product_id] * 4


def test_iter_product_images_streams_worksheet_and_shared_strings_xml(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """大 worksheet/sharedStrings 解析不能把整个 ZIP 条目交给 archive.read。"""
    workbook = tmp_path / "streamed-xml.xlsx"
    write_tencent_workbook(
        workbook,
        product_cell='<c r="F2" t="s"><v>0</v></c>',
        include_shared_strings=True,
    )
    read_paths: list[str] = []
    original_read = ZipFile.read

    def record_read(archive: ZipFile, name: str, *args: object, **kwargs: object) -> bytes:
        read_paths.append(name)
        return original_read(archive, name, *args, **kwargs)

    monkeypatch.setattr(ZipFile, "read", record_read)

    images = list(iter_product_images(workbook))

    assert [image.product_id for image in images] == ["SKU-共享"] * 4
    assert "xl/worksheets/sheet1.xml" not in read_paths
    assert "xl/sharedStrings.xml" not in read_paths


def test_iter_product_images_rejects_workbook_without_carpet_sheet(tmp_path: Path) -> None:
    """目标工作表被改名时必须给出稳定的结构错误。"""
    workbook = tmp_path / "wrong-sheet.xlsx"
    write_tencent_workbook(workbook, sheet_name="其他图片")

    with pytest.raises(WorkbookStructureError, match="^找不到工作表：地毯图片$"):
        list(iter_product_images(workbook))


def test_iter_product_images_skips_anchored_row_without_product_id(tmp_path: Path) -> None:
    """图片所在行缺少 F 列商品 ID 时不产生可导入图片。"""
    workbook = tmp_path / "missing-product-id.xlsx"
    write_tencent_workbook(workbook, product_cell="")

    assert list(iter_product_images(workbook)) == []
