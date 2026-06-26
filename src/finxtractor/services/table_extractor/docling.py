"""Docling (TableFormer) table-extraction backend."""
from __future__ import annotations

from pathlib import Path

from loguru import logger

from .base import ParsedTable


class DoclingTableExtractor:
    """Extract tables with Docling's TableFormer. Settings come from the
    `docling` provider block in config/models.yaml -> table_extraction."""

    def __init__(self, mode: str = "ACCURATE", do_ocr: bool = False):
        self.mode = mode
        self.do_ocr = do_ocr
        self._converter = None  # built lazily, reused across pages

    def _build_converter(self):
        # Lazy import so the package imports without docling installed; only this
        # backend needs it (mirrors the lazy provider imports in services/llm/).
        from docling.document_converter import DocumentConverter, PdfFormatOption
        from docling.datamodel.base_models import InputFormat
        from docling.datamodel.pipeline_options import PdfPipelineOptions, TableFormerMode

        logger.debug("Building docling PDF converter (mode={}, do_ocr={})",
                     self.mode, self.do_ocr)
        opts = PdfPipelineOptions(do_table_structure=True)
        opts.table_structure_options.mode = TableFormerMode[self.mode]  # ACCURATE | FAST
        opts.do_ocr = self.do_ocr
        return DocumentConverter(
            format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=opts)}
        )

    def extract_tables(self, pdf: Path | str, page_number: int) -> list[ParsedTable]:
        if self._converter is None:
            self._converter = self._build_converter()
        result = self._converter.convert(str(pdf), page_range=(page_number, page_number))
        tables: list[ParsedTable] = []
        for t in result.document.tables:
            bbox = None
            if t.prov:
                b = t.prov[0].bbox
                bbox = (b.l, b.t, b.r, b.b)  # four floats, per schema
            tables.append(ParsedTable(df=t.export_to_dataframe(), bbox=bbox))
        return tables
