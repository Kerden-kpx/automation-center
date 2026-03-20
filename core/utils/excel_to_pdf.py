# !/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Excel to PDF conversion utilities.
Uses Microsoft Excel or WPS COM interface to preserve formatting.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Optional, List

logger = logging.getLogger("Common.ExcelToPdf")


def excel_to_pdf(excel_path: str, pdf_path: Optional[str] = None) -> str:
    """
    Convert Excel file to PDF using Microsoft Excel/WPS COM interface.

    Args:
        excel_path: Path to the Excel file.
        pdf_path: Optional output PDF path. If not provided,
                  uses the same name as the Excel file with .pdf extension.

    Returns:
        Path to the generated PDF file.
    """
    try:
        import win32com.client
    except ImportError as exc:
        logger.error("缺少 pywin32 库，请运行: pip install pywin32")
        raise

    excel_path = Path(excel_path).resolve()
    if pdf_path is None:
        pdf_path = excel_path.with_suffix('.pdf')
    else:
        pdf_path = Path(pdf_path).resolve()

    if not excel_path.exists():
        raise FileNotFoundError(f"Excel 文件不存在: {excel_path}")

    logger.info("正在读取 Excel 文件: %s", excel_path)

    app = None
    wb = None

    app_names = ["Ket.Application", "KET.Application", "Excel.Application"]
    for app_name in app_names:
        try:
            app = win32com.client.Dispatch(app_name)
            logger.info("使用 %s 进行转换", app_name)
            break
        except Exception:
            continue

    if app is None:
        raise RuntimeError("未找到可用的 WPS 或 Excel 应用程序")

    try:
        app.Visible = False
        app.DisplayAlerts = False

        wb = app.Workbooks.Open(str(excel_path))
        time.sleep(2)

        logger.info("正在生成 PDF: %s", pdf_path)
        max_retries = 3
        for attempt in range(max_retries):
            try:
                wb.ExportAsFixedFormat(
                    Type=0,  # xlTypePDF
                    Filename=str(pdf_path),
                    Quality=0,  # xlQualityStandard
                    IncludeDocProperties=True,
                    IgnorePrintAreas=False,
                    OpenAfterPublish=False
                )
                break
            except Exception:
                if attempt < max_retries - 1:
                    logger.warning("导出尝试 %s 失败，等待后重试...", attempt + 1)
                    time.sleep(2)
                else:
                    raise

        logger.info("✅ PDF 生成成功: %s", pdf_path)
        return str(pdf_path)
    finally:
        if wb:
            try:
                wb.Close(SaveChanges=False)
            except Exception:
                pass
        if app:
            try:
                app.Quit()
            except Exception:
                pass


def batch_excel_to_pdf(directory: str, output_dir: Optional[str] = None) -> List[str]:
    """
    Batch convert all Excel files in a directory to PDF.

    Args:
        directory: Directory containing Excel files.
        output_dir: Optional output directory for PDFs.

    Returns:
        List of generated PDF paths.
    """
    directory = Path(directory)
    if output_dir:
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
    else:
        output_dir = directory

    pdf_paths: List[str] = []
    excel_files = list(directory.glob("*.xlsx")) + list(directory.glob("*.xls"))

    if not excel_files:
        logger.warning("目录中未找到 Excel 文件: %s", directory)
        return pdf_paths

    for excel_file in excel_files:
        try:
            pdf_path = output_dir / f"{excel_file.stem}.pdf"
            result = excel_to_pdf(str(excel_file), str(pdf_path))
            pdf_paths.append(result)
        except Exception as exc:
            logger.error("转换失败 %s: %s", excel_file, exc)

    return pdf_paths


def excel_sheet_to_pdf(excel_path: str, sheet_name: str, pdf_path: Optional[str] = None) -> str:
    """
    Export a single worksheet to PDF using Microsoft Excel/WPS COM interface.

    Args:
        excel_path: Path to the Excel file.
        sheet_name: Worksheet name to export.
        pdf_path: Optional output PDF path. If not provided,
                  uses the sheet name with .pdf extension in the same folder.

    Returns:
        Path to the generated PDF file.
    """
    try:
        import win32com.client
    except ImportError as exc:
        logger.error("缺少 pywin32 库，请运行: pip install pywin32")
        raise

    excel_path = Path(excel_path).resolve()
    if pdf_path is None:
        pdf_path = excel_path.with_name(f"{sheet_name}.pdf")
    else:
        pdf_path = Path(pdf_path).resolve()

    if not excel_path.exists():
        raise FileNotFoundError(f"Excel 文件不存在: {excel_path}")

    logger.info("正在读取 Excel 文件: %s", excel_path)

    app = None
    wb = None

    app_names = ["Ket.Application", "KET.Application", "Excel.Application"]
    for app_name in app_names:
        try:
            app = win32com.client.Dispatch(app_name)
            logger.info("使用 %s 进行转换", app_name)
            break
        except Exception:
            continue

    if app is None:
        raise RuntimeError("未找到可用的 WPS 或 Excel 应用程序")

    try:
        app.Visible = False
        app.DisplayAlerts = False

        wb = app.Workbooks.Open(str(excel_path))
        time.sleep(2)

        try:
            ws = wb.Worksheets(sheet_name)
        except Exception:
            raise ValueError(f"未找到工作表: {sheet_name}")

        logger.info("正在生成 PDF: %s", pdf_path)
        ws.ExportAsFixedFormat(
            Type=0,  # xlTypePDF
            Filename=str(pdf_path),
            Quality=0,  # xlQualityStandard
            IncludeDocProperties=True,
            IgnorePrintAreas=False,
            OpenAfterPublish=False
        )

        logger.info("✅ PDF 生成成功: %s", pdf_path)
        return str(pdf_path)
    finally:
        if wb:
            try:
                wb.Close(SaveChanges=False)
            except Exception:
                pass
        if app:
            try:
                app.Quit()
            except Exception:
                pass
