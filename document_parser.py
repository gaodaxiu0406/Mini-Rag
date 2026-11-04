import csv
import shutil
import subprocess
import tempfile
from html.parser import HTMLParser
from io import BytesIO, StringIO
from pathlib import Path
from zipfile import BadZipFile

import markdown
import pdfplumber
import xlrd
from docx import Document
from docx.opc.exceptions import PackageNotFoundError
from docx.table import Table
from docx.text.paragraph import Paragraph
from openpyxl import load_workbook
from openpyxl.utils.exceptions import InvalidFileException
from pypdf import PdfReader
from pypdf.errors import PdfReadError
from pdfminer.pdfexceptions import PDFException
from xlrd.biffh import XLRDError


class _MarkdownTextExtractor(HTMLParser):
    _BLOCK_TAGS = {
        "blockquote",
        "br",
        "div",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "li",
        "ol",
        "p",
        "pre",
        "table",
        "tr",
        "ul",
    }

    def __init__(self):
        super().__init__()
        self.parts = []

    def handle_starttag(self, tag, attrs):
        del attrs
        if tag in self._BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self._BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data):
        self.parts.append(data)


def _format_rows(rows):
    lines = []
    for row in rows:
        values = ["" if value is None else str(value).strip() for value in row]
        if any(values):
            lines.append(" | ".join(values))
    return "\n".join(lines)


def _extract_xlsx(content):
    try:
        workbook = load_workbook(BytesIO(content), read_only=True, data_only=True)
    except (BadZipFile, InvalidFileException, OSError, ValueError) as error:
        raise ValueError("无法解析该 Excel 文件，请上传有效的 .xlsx 文件。") from error
    try:
        parts = []
        for sheet in workbook.worksheets:
            parts.append(f"【工作表：{sheet.title}】")
            parts.append(_format_rows(sheet.iter_rows(values_only=True)))
        return "\n".join(parts)
    finally:
        workbook.close()


def _extract_xls(content):
    try:
        workbook = xlrd.open_workbook(file_contents=content, on_demand=True)
    except (XLRDError, OSError, ValueError) as error:
        raise ValueError("无法解析该 Excel 文件，请上传有效的 .xls 文件。") from error
    try:
        parts = []
        for sheet in workbook.sheets():
            parts.append(f"【工作表：{sheet.name}】")
            rows = (
                [sheet.cell_value(row_index, col_index) for col_index in range(sheet.ncols)]
                for row_index in range(sheet.nrows)
            )
            parts.append(_format_rows(rows))
        return "\n".join(parts)
    finally:
        workbook.release_resources()


def _extract_legacy_doc(content):
    converter = shutil.which("antiword")
    if converter:
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "document.doc"
            source.write_bytes(content)
            try:
                result = subprocess.run(
                    [converter, str(source)],
                    capture_output=True,
                    timeout=60,
                    check=False,
                )
            except subprocess.TimeoutExpired as error:
                raise ValueError("解析 .doc 文件超时，请尝试另存为 .docx 后上传。") from error
            if result.returncode != 0:
                raise ValueError("无法解析该 .doc 文件，请确认文件有效或另存为 .docx。")
            return result.stdout.decode("utf-8", errors="replace")

    converter = (
        shutil.which("textutil")
        or shutil.which("libreoffice")
        or shutil.which("soffice")
    )
    if not converter:
        raise ValueError(
            "解析旧版 .doc 需要 macOS textutil、LibreOffice 或 Antiword；"
            "也可以先将文件另存为 .docx 后上传。"
        )
    with tempfile.TemporaryDirectory() as temp_dir:
        source = Path(temp_dir) / "document.doc"
        source.write_bytes(content)
        try:
            if Path(converter).name == "textutil":
                command = [
                    converter,
                    "-convert",
                    "txt",
                    "-output",
                    str(Path(temp_dir) / "document.txt"),
                    str(source),
                ]
            else:
                command = [
                    converter,
                    "--headless",
                    "--convert-to",
                    "txt:Text",
                    "--outdir",
                    temp_dir,
                    str(source),
                ]
            result = subprocess.run(
                command, capture_output=True, timeout=60, check=False
            )
        except subprocess.TimeoutExpired as error:
            raise ValueError("解析 .doc 文件超时，请尝试另存为 .docx 后上传。") from error
        if result.returncode != 0:
            raise ValueError("无法解析该 .doc 文件，请确认文件有效或另存为 .docx。")
        converted = Path(temp_dir) / "document.txt"
        if not converted.is_file():
            raise ValueError("LibreOffice 未能转换该 .doc 文件，请尝试另存为 .docx。")
        return converted.read_text(encoding="utf-8", errors="replace")


def _extract_docx(content):
    try:
        document = Document(BytesIO(content))
    except (BadZipFile, PackageNotFoundError, OSError, ValueError) as error:
        raise ValueError("无法解析该 Word 文件，请上传有效的 .docx 文件。") from error

    parts = []
    for child in document.element.body.iterchildren():
        if child.tag.endswith("}p"):
            parts.append(Paragraph(child, document).text)
        elif child.tag.endswith("}tbl"):
            table = Table(child, document)
            parts.append(_format_rows(
                [[cell.text for cell in row.cells] for row in table.rows]
            ))
    return "\n".join(parts)


def _extract_pdf(content):
    try:
        reader = PdfReader(BytesIO(content))
    except (OSError, PdfReadError, ValueError) as error:
        raise ValueError("无法解析该 PDF 文件。") from error
    if reader.is_encrypted:
        raise ValueError("暂不支持加密的 PDF 文件。")
    try:
        layout_pages = [
            page.extract_text(extraction_mode="layout") or ""
            for page in reader.pages
        ]
    except (OSError, PdfReadError, ValueError) as error:
        raise ValueError("无法解析该 PDF 文件。") from error

    table_parts = []
    scanned_pages = []
    try:
        with pdfplumber.open(BytesIO(content)) as pdf:
            for page_number, page in enumerate(pdf.pages, start=1):
                if page_number <= len(layout_pages) and not layout_pages[page_number - 1].strip():
                    fallback_text = page.extract_text(layout=True) or ""
                    if fallback_text:
                        layout_pages[page_number - 1] = fallback_text
                    else:
                        scanned_pages.append(page_number)
                tables = page.extract_tables()
                for table_number, table in enumerate(tables, start=1):
                    rows = _format_rows(table)
                    if rows:
                        table_parts.append(
                            f"【PDF 表格：第 {page_number} 页，表格 {table_number}】\n{rows}"
                        )
                if not tables:
                    text_tables = page.extract_tables({
                        "vertical_strategy": "text",
                        "horizontal_strategy": "text",
                        "min_words_vertical": 2,
                        "min_words_horizontal": 1,
                    })
                    for table_number, table in enumerate(text_tables, start=1):
                        rows = _format_rows(table)
                        if rows:
                            table_parts.append(
                                f"【PDF 表格：第 {page_number} 页，表格 {table_number}】\n{rows}"
                            )
    except (OSError, PDFException, ValueError) as error:
        raise ValueError("PDF 表格解析失败，请确认文件有效后重试。") from error

    if scanned_pages:
        if not any(text.strip() for text in layout_pages) and not table_parts:
            page_list = "、".join(map(str, scanned_pages))
            raise ValueError(
                f"PDF 第 {page_list} 页未提取到可搜索文本，可能是扫描版；"
                "本项目目前尚未支持 OCR。请使用可搜索 PDF，或提供相关页面/样例文件以便进一步定位。"
            )
        page_list = "、".join(map(str, scanned_pages))
        table_parts.append(
            f"【OCR 提示】第 {page_list} 页未提取到文本，可能是扫描页；"
            "本项目目前不支持 OCR，请核对原文或提供相关页面以便进一步定位。"
        )
    return "\n\n".join([*layout_pages, *table_parts])


def extract_document_text(filename, content):
    extension = Path(filename).suffix.lower()
    if extension in {".txt", ".md", ".csv"}:
        try:
            text = content.decode("utf-8-sig")
        except UnicodeDecodeError as error:
            raise ValueError("文件必须使用 UTF-8 编码。") from error
        if extension == ".md":
            extractor = _MarkdownTextExtractor()
            extractor.feed(markdown.markdown(text, extensions=["fenced_code", "tables"]))
            text = "".join(extractor.parts)
        elif extension == ".csv":
            text = _format_rows(csv.reader(StringIO(text)))
    elif extension == ".pdf":
        text = _extract_pdf(content)
    elif extension == ".docx":
        text = _extract_docx(content)
    elif extension == ".doc":
        text = _extract_legacy_doc(content)
    elif extension == ".xlsx":
        text = _extract_xlsx(content)
    elif extension == ".xls":
        text = _extract_xls(content)
    else:
        raise ValueError(
            "不支持此文件格式，请上传 PDF、Word (.doc/.docx)、Excel (.xls/.xlsx)、"
            "CSV、Markdown (.md) 或 TXT 文件。"
        )

    if not text.strip():
        if extension == ".pdf":
            raise ValueError(
                "PDF 中未提取到可搜索文本；扫描版 PDF 需要 OCR，本项目目前尚未支持。"
                "如果重新上传后某些列表仍缺失，请提供相关页面或样例文件以便进一步定位。"
            )
        raise ValueError("文件中没有可用于入库的文本内容。")
    return text
