"""pytest 共用 fixtures。"""
import sys
import os
import json
from pathlib import Path

# 把 scripts/ 加入 sys.path，让测试能直接 import 脚本模块
_SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import pytest


@pytest.fixture
def scripts_dir():
    """返回 scripts 目录的 Path 对象。"""
    return _SCRIPTS_DIR


@pytest.fixture
def fixtures_dir():
    """返回 fixtures 目录的 Path 对象。"""
    return Path(__file__).resolve().parent / "fixtures"


@pytest.fixture
def current_year():
    """固定当前年份为 2026，避免跨年测试不稳定。"""
    return 2026


@pytest.fixture
def papers_valid(fixtures_dir):
    """有效核心证据样本（含 RCT + 系统综述 + 期刊论文，有 DOI 和年份）。"""
    with open(fixtures_dir / "papers_valid.json", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
def papers_mock(fixtures_dir):
    """全 mock 样本（is_mock=True）。"""
    with open(fixtures_dir / "papers_mock.json", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
def papers_preprint(fixtures_dir):
    """预印本样本（arXiv DOI）。"""
    with open(fixtures_dir / "papers_preprint.json", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
def papers_future_year(fixtures_dir):
    """未来年份样本。"""
    with open(fixtures_dir / "papers_future_year.json", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
def papers_regulatory(fixtures_dir):
    """监管批准样本（FDA_NMPA_approval + 官方文件编号）。"""
    with open(fixtures_dir / "papers_regulatory.json", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
def papers_duplicate_doi(fixtures_dir):
    """重复 DOI 样本。"""
    with open(fixtures_dir / "papers_duplicate_doi.json", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
def papers_ai_conference(fixtures_dir):
    """P1-1: 5 篇 AI 会议论文样本（AI 域 override 后基础权重 1.5）。"""
    with open(fixtures_dir / "papers_ai_conference.json", encoding="utf-8") as f:
        return json.load(f)
