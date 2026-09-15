"""共用配置加载模块。

提供 evidence_weights.json 的单一事实源读取，避免多个脚本各自硬编码 domain choices
导致漂移（如 search_papers.py 缺 "default" 而 score_evidence.py 有）。
"""
import json
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)


def _get_config_path():
    """返回 evidence_weights.json 的路径。"""
    return Path(__file__).parent / "config" / "evidence_weights.json"


def load_config():
    """加载 evidence_weights.json 配置。配置文件缺失时 fail-fast。"""
    with open(_get_config_path(), "r", encoding="utf-8") as f:
        return json.load(f)


def _get_config_file(name):
    """返回 scripts/config/ 下指定配置文件的路径。"""
    return Path(__file__).parent / "config" / name


def load_json_config(name):
    """通用 JSON 配置加载器。文件缺失时 fail-fast。"""
    with open(_get_config_file(name), "r", encoding="utf-8") as f:
        return json.load(f)


def get_validity_states():
    """从 validity_states.json 读取 6 个有效性状态枚举。"""
    return tuple(load_json_config("validity_states.json")["validity_states"])


def get_internal_jargon():
    """从 internal_jargon.json 读取内部黑话列表。"""
    return tuple(load_json_config("internal_jargon.json")["internal_jargon"])


def get_conclusion_options():
    """从 conclusion_options.json 读取三选一结论选项。"""
    return tuple(load_json_config("conclusion_options.json")["conclusion_options"])


def get_disclaimer_phrases():
    """从 disclaimer_phrases.json 读取免责声明关键短语。"""
    return load_json_config("disclaimer_phrases.json")


def get_valid_domains():
    """从 evidence_weights.json 的 domain_map 读取所有有效 domain 键。

    返回排序后的列表，供 argparse choices 使用，确保两个脚本的 --domain 参数一致。
    """
    config = load_config()
    return sorted(config["domain_map"].keys())


def load_dotenv():
    """从脚本所在目录及上级目录查找 .env 文件并加载到 os.environ。

    已存在的环境变量不会被覆盖（尊重 shell 中的手动设置）。
    使用纯标准库实现，不依赖 python-dotenv。
    """
    current = Path(__file__).resolve().parent
    for directory in [current] + list(current.parents)[:3]:
        env_path = directory / ".env"
        if env_path.is_file():
            _parse_env_file(env_path)
            return


def _parse_env_file(env_path):
    """解析单个 .env 文件并写入 os.environ（不覆盖已有变量）。"""
    try:
        with open(env_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if key and key not in os.environ:
                    os.environ[key] = value
    except (OSError, UnicodeDecodeError) as e:
        logger.warning("加载 .env 失败 (%s): %s", env_path, e)
