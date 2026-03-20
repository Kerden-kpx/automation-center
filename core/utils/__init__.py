# !/usr/bin/env python
# -*- coding: utf-8 -*-
"""Common Utilities for automation projects."""

from .excel_to_pdf import (
    excel_to_pdf,
    batch_excel_to_pdf,
    excel_sheet_to_pdf,
)

from .file_archive import (
    zip_folder,
)

from .excel_registry import (
    RegistryConfig,
    create_next_entry,
    ensure_target_folder,
    get_entry_folder_path,
    get_latest_entry,
)
from .invoice_registry import register_invoice

__all__ = [
    "RegistryConfig",
    "create_next_entry",
    "ensure_target_folder",
    "get_entry_folder_path",
    "get_latest_entry",
    "excel_to_pdf",
    "batch_excel_to_pdf",
    "register_invoice",
]
