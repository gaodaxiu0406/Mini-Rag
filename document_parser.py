from html.parser import HTMLParser
from io import BytesIO
from pathlib import Path

import markdown
from docx import Document
from docx.opc.exceptions import PackageNotFoundError
from pypdf import PdfReader
from pypdf.errors import PdfReadError


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
        if tag in self._BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self._BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data):
        self.parts.append(data)


def extract_document_text(filename, content):
    extension = Path(filename).suffix.lower()
    if extension in {".txt", ".md"}:
        try:
            text = content.decode("utf-8-sig")
        except UnicodeDecodeError as error:
            raise ValueError("文件必须使用 UTF-8 编码。") from error
        if extension == ".md":
            extractor = _MarkdownTextExtractor()
            extractor.feed(markdown.markdown(text, extensions=["fenced_code", "tables"]))
            text = "".join(extractor.parts)
    elif extension == ".pdf":
        try:
            reader = PdfReader(BytesIO(content))
            if reader.is_encrypted:
                raise ValueError("暂不支持加密的 PDF 文件。")
            text = "\n".join(page.extract_text() or "" for page in reader.pages)
        except PdfReadError as error:
            raise ValueError("无法解析该 PDF 文件。") from error
    elif extension == ".docx":
        try:
            document = Document(BytesIO(content))
        except PackageNotFoundError as error:
            raise ValueError("无法解析该 Word 文件，请上传有效的 .docx 文件。") from error
        parts = [paragraph.text for paragraph in document.paragraphs]
        for table in document.tables:
            parts.extend(
                "\t".join(cell.text for cell in row.cells)
                for row in table.rows
            )
        text = "\n".join(parts)
    else:
        raise ValueError("不支持此文件格式，请上传 PDF、Word (.docx)、Markdown (.md) 或 TXT 文件。")

    if not text.strip():
        if extension == ".pdf":
            raise ValueError("PDF 中未提取到可搜索文本；扫描版 PDF 暂不支持 OCR。")
        raise ValueError("文件中没有可用于入库的文本内容。")
    return text
