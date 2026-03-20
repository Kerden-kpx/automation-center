# !/usr/bin/env python
# -*- coding: utf-8 -*-
"""
File archive utilities.
"""

from __future__ import annotations

import os
import zipfile
from pathlib import Path
from typing import Optional


def zip_folder(folder_path: str, zip_path: Optional[str] = None) -> str:
    """
    Compress a folder into a zip file.

    Args:
        folder_path: Folder to compress.
        zip_path: Optional output zip file path. If not provided,
                  uses the folder name with .zip in the same parent dir.

    Returns:
        Path to the generated zip file.
    """
    folder = Path(folder_path).resolve()
    if not folder.exists() or not folder.is_dir():
        raise FileNotFoundError(f"文件夹不存在: {folder}")

    if zip_path is None:
        zip_path = folder.with_suffix('.zip')
    else:
        zip_path = Path(zip_path).resolve()

    with zipfile.ZipFile(zip_path, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
        for root, _, files in os.walk(folder):
            for filename in files:
                full_path = Path(root) / filename
                arc_name = full_path.relative_to(folder)
                zf.write(full_path, arc_name.as_posix())

    return str(zip_path)
