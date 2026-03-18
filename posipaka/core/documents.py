"""Document Processing — PDF, DOCX, XLSX, CSV."""

from __future__ import annotations

import asyncio
from pathlib import Path

from posipaka.security.injection import sanitize_external_content


async def process_pdf(file_path: Path, question: str = "") -> str:
    """Витягнути текст з PDF."""
    try:
        import pdfplumber

        def _extract() -> str:
            text_parts = []
            with pdfplumber.open(str(file_path)) as pdf:
                for i, page in enumerate(pdf.pages[:50]):  # MAX_FILE_PAGES
                    text = page.extract_text() or ""
                    if text:
                        text_parts.append(f"--- Page {i + 1} ---\n{text}")
            return "\n\n".join(text_parts)

        text = await asyncio.to_thread(_extract)
        if not text:
            return "PDF порожній або не містить тексту."
        return sanitize_external_content(text[:10000], source=str(file_path))
    except ImportError:
        return "pdfplumber не встановлено: pip install pdfplumber"
    except Exception as e:
        return f"Помилка PDF: {e}"


async def process_docx(file_path: Path) -> str:
    """Витягнути текст з DOCX."""
    try:
        from docx import Document

        def _extract() -> str:
            doc = Document(str(file_path))
            return "\n".join(p.text for p in doc.paragraphs if p.text)

        text = await asyncio.to_thread(_extract)
        return sanitize_external_content(text[:10000], source=str(file_path))
    except ImportError:
        return "python-docx не встановлено: pip install python-docx"
    except Exception as e:
        return f"Помилка DOCX: {e}"


async def analyze_spreadsheet(file_path: Path, question: str = "") -> str:
    """Аналіз CSV/XLSX через pandas."""
    try:
        import pandas as pd

        def _analyze() -> str:
            suffix = file_path.suffix.lower()
            if suffix == ".csv":
                df = pd.read_csv(str(file_path), nrows=1000)
            elif suffix in (".xlsx", ".xls"):
                df = pd.read_excel(str(file_path), nrows=1000)
            else:
                return f"Непідтримуваний формат: {suffix}"

            lines = [
                f"Розміри: {df.shape[0]} рядків × {df.shape[1]} колонок",
                f"Колонки: {', '.join(df.columns.tolist()[:20])}",
                f"\nПерші 5 рядків:\n{df.head().to_string()}",
                f"\nСтатистика:\n{df.describe().to_string()}",
            ]
            return "\n".join(lines)

        result = await asyncio.to_thread(_analyze)
        return sanitize_external_content(result[:8000], source=str(file_path))
    except ImportError:
        return "pandas не встановлено: pip install pandas openpyxl"
    except Exception as e:
        return f"Помилка аналізу: {e}"


DOCUMENT_PROCESSORS = {
    ".pdf": process_pdf,
    ".docx": process_docx,
    ".doc": process_docx,
    ".csv": analyze_spreadsheet,
    ".xlsx": analyze_spreadsheet,
    ".xls": analyze_spreadsheet,
}


async def process_document(file_path: Path, question: str = "") -> str:
    """Обробити документ відповідним процесором."""
    suffix = file_path.suffix.lower()
    processor = DOCUMENT_PROCESSORS.get(suffix)
    if not processor:
        # Plain text
        if suffix in (".txt", ".md", ".json", ".yaml", ".yml", ".py", ".js"):
            text = file_path.read_text(encoding="utf-8", errors="replace")[:10000]
            return sanitize_external_content(text, source=str(file_path))
        return f"Непідтримуваний формат: {suffix}"

    return await processor(file_path, question)
