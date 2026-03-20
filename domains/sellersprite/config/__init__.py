#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Static configuration for SellerSprite flows."""

from __future__ import annotations

import os
from pathlib import Path

# DB target used by platform.data.client
SELLERSPRITE_CCP_DB_NAME = "bi_amazon"

# Project root: .../automation-center
PROJECT_ROOT = Path(__file__).resolve().parents[3]

# Local runtime paths
SELLERSPRITE_DOWNLOAD_BASE_DIR = PROJECT_ROOT / "domains" / "sellersprite" / "files"
SELLERSPRITE_UC_DRIVER_PATH = (
    PROJECT_ROOT
    / "web"
    / "shared"
    / "chromedriver"
    / ("chromedriver.exe" if os.name == "nt" else "chromedriver")
)
SELLERSPRITE_UC_USER_DATA_DIR = PROJECT_ROOT / "web" / "shared" / "chrome-user-data" / "uc-sellersprite"

# UC runtime options
SELLERSPRITE_UC_HEADLESS = False
SELLERSPRITE_UC_USE_SUBPROCESS = False
SELLERSPRITE_UC_VERSION_MAIN: int | None = None
SELLERSPRITE_UC_KEEP_OPEN = False

# Export-log polling options
SELLERSPRITE_EXPORT_LOG_URL = "https://www.sellersprite.com/v2/export-log"
SELLERSPRITE_EXPORT_LOG_WAIT_MINUTES = 3
