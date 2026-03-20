#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Run Amazon pipelines per configured category id."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

import yaml

from ..repositories.site_pipeline_status_repo import get_today_success_job_keys, upsert_status


PROJECT_ROOT = Path(__file__).resolve().parents[3]
TARGET_CONFIG_PATH = PROJECT_ROOT / "domains" / "amazon" / "selectors" / "amazon_target_urls.yaml"


def _load_site_pipelines() -> List[Dict[str, Any]]:
    if not TARGET_CONFIG_PATH.exists():
        raise RuntimeError(f"Missing target config: {TARGET_CONFIG_PATH}")
    with TARGET_CONFIG_PATH.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise RuntimeError(f"Invalid target config: {TARGET_CONFIG_PATH}")

    jobs: List[Dict[str, Any]] = []
    for target_id, item in data.items():
        if not isinstance(item, dict):
            continue
        site = str(item.get("site") or "").strip().upper()
        name = str(item.get("name") or "").strip()
        if not site or not name:
            continue
        jobs.append(
            {
                "id": str(target_id).strip(),
                "site": site,
                "name": name,
            }
        )
    return jobs


def _log(message: str) -> None:
    text = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] [AmazonSitePipeline] {message}"
    try:
        print(text)
    except UnicodeEncodeError:
        encoding = sys.stdout.encoding or "utf-8"
        safe_text = text.encode(encoding, errors="replace").decode(encoding, errors="replace")
        print(safe_text)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run amazon -> sellersprite -> amazon pipeline per id")
    parser.add_argument(
        "--id",
        default="",
        help="Comma separated category IDs to run, e.g. 1,2",
    )
    parser.add_argument(
        "--force-rerun-success",
        action="store_true",
        help="Rerun sites even if status.xlsx marks them success for today",
    )
    return parser.parse_args()


def _filter_jobs(id_filter: str, all_jobs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    normalized = str(id_filter or "").strip()
    if not normalized:
        return all_jobs
    if normalized.upper() == "ALL":
        return all_jobs
    selected = {item.strip() for item in normalized.split(",") if item.strip()}
    return [job for job in all_jobs if str(job.get("id") or "").strip() in selected]


def _run_step(module_name: str, extra_args: List[str] | None = None, extra_env: Dict[str, str] | None = None) -> None:
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    if extra_env:
        env.update(extra_env)
    cmd = [sys.executable, "-m", module_name]
    if extra_args:
        cmd.extend(extra_args)
    _log(f"执行: {' '.join(cmd)}")
    subprocess.run(cmd, cwd=PROJECT_ROOT, env=env, check=True)


def _now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _today_text() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _get_today_success_job_keys() -> set[tuple[str, str]]:
    return get_today_success_job_keys(_today_text())


def _run_site_pipeline(job: Dict[str, Any]) -> None:
    job_id = str(job.get("id") or "").strip()
    site = str(job.get("site") or "").strip().upper()
    if not site:
        raise RuntimeError(f"站点配置缺少 site: {job}")
    if not job_id:
        raise RuntimeError(f"站点配置缺少 id: {job}")

    name = str(job.get("name") or site).strip() or site
    run_date = _today_text()
    started_at = _now_text()
    upsert_status(run_date, site, job_id, name, "running", started_at=started_at, ended_at="", error="")
    _log(f"[{site}] 流水线开始: id={job_id}, category={name}")

    try:
        _run_step("domains.amazon.flows.amazon_best_sellers", ["--id", job_id])
        _run_step("domains.sellersprite.flows.sellersprite_ccp", ["--id", job_id])
        _run_step("domains.amazon.flows.amazon_product_details", ["--id", job_id])
        upsert_status(run_date, site, job_id, name, "success", started_at=started_at, ended_at=_now_text(), error="")
    except Exception as exc:
        upsert_status(run_date, site, job_id, name, "failed", started_at=started_at, ended_at=_now_text(), error=str(exc))
        raise
    _log(f"[{site}] 流水线完成: id={job_id}, category={name}")


def main() -> None:
    args = _parse_args()
    all_jobs = _load_site_pipelines()
    jobs = _filter_jobs(args.id, all_jobs)
    if not jobs:
        raise SystemExit("No pipeline jobs selected.")

    if not args.force_rerun_success:
        success_job_keys = _get_today_success_job_keys()
        if success_job_keys:
            before = len(jobs)
            jobs = [
                job
                for job in jobs
                if (
                    str(job.get("site") or "").strip().upper(),
                    str(job.get("id") or "").strip(),
                ) not in success_job_keys
            ]
            skipped = before - len(jobs)
            if skipped > 0:
                _log(f"检测到今日已成功任务，自动跳过 {skipped} 个: {sorted(success_job_keys)}")
    if not jobs:
        _log("本次无可执行站点（都已成功），结束。")
        return

    _log(f"待执行站点数: {len(jobs)}")
    _log("执行策略: 每个 id 顺序执行 amazon_best_sellers -> sellersprite_ccp -> amazon_product_details")

    failed: List[str] = []
    for job in jobs:
        site = str(job.get("site") or "").strip().upper()
        job_id = str(job.get("id") or "").strip()
        try:
            _run_site_pipeline(job)
        except Exception as exc:
            failed.append(f"{job_id}/{site}: {exc}")
            _log(f"[{site}] 流水线失败: id={job_id}")

    if failed:
        for item in failed:
            _log(f"失败: {item}")
        raise SystemExit("流水线部分任务失败，请查看日志。")

    _log("所有任务已完成。")


if __name__ == "__main__":
    main()
