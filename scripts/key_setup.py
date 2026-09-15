"""InterSci-KD API Key 引导式配置模块。

首次运行脚本时检测 SCP_HUB_API_KEY 是否已配置：
- 已配置（os.environ 或 .env 文件）→ 直接返回，不打扰用户
- 缺失 → 打印友好提示，交互式引导用户输入 Key，自动写入 .env 文件

设计参考：HuggingFace CLI、AWS CLI、gcloud CLI 的首次运行引导模式。
Key 永远不进 git 仓库（.env 已在 .gitignore 排除），用户自行保管。

用法（由其他脚本调用）：
    from key_setup import ensure_scp_key
    api_key = ensure_scp_key()  # 返回 Key 字符串；用户拒绝配置则返回空串
"""
import os
import sys
from pathlib import Path


# 必填 Key 列表：变量名 → (申请地址, 用途说明)
REQUIRED_KEYS = {
    "SCP_HUB_API_KEY": (
        "https://scp.intern-ai.org.cn",
        "SCP 平台通用 API Key（11 个数据工具共用，10 个 MCP 端点，用于文献检索与证据采集）",
    ),
}

# 可选 Key 列表：变量名 → (申请地址, 用途说明)
OPTIONAL_KEYS = {
    "INTERNLM_API_KEY": (
        "https://intern-ai.org.cn",
        "书生大模型 API Key（可选，仅 LLM_BACKEND=internlm 时需要）",
    ),
    "COMPETITION_API_KEY": (
        None,
        "竞赛 API Key（可选，仅赛事参与者需要，由赛事方提供）",
    ),
}


def _find_env_file():
    """从脚本所在目录及上级 3 层目录查找 .env 文件。返回 Path 或 None。"""
    current = Path(__file__).resolve().parent
    for directory in [current] + list(current.parents)[:3]:
        env_path = directory / ".env"
        if env_path.is_file():
            return env_path
    # 默认写到脚本所在目录的上级（项目根目录）
    return current.parent / ".env"


def _find_example_file():
    """查找 .env.example 模板文件位置，返回 Path 或 None。"""
    current = Path(__file__).resolve().parent
    for directory in [current] + list(current.parents)[:3]:
        example_path = directory / ".env.example"
        if example_path.is_file():
            return example_path
    return None


def _load_dotenv_self():
    """从脚本所在目录及上级目录加载 .env 到 os.environ（不覆盖已存在的环境变量）。"""
    current = Path(__file__).resolve().parent
    for directory in [current] + list(current.parents)[:3]:
        env_path = directory / ".env"
        if env_path.is_file():
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
            except Exception:
                pass
            break


def _append_to_env_file(env_path, key_name, key_value):
    """把 KEY=value 追加到 .env 文件末尾。若文件不存在则创建。"""
    env_path = Path(env_path)
    # 确保父目录存在
    env_path.parent.mkdir(parents=True, exist_ok=True)

    # 读取现有内容，检查 Key 是否已存在（可能值为空）
    existing_lines = []
    key_found = False
    if env_path.is_file():
        with open(env_path, encoding="utf-8") as f:
            existing_lines = f.readlines()
        for i, line in enumerate(existing_lines):
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            k, _, _ = stripped.partition("=")
            if k.strip() == key_name:
                # 替换该行
                existing_lines[i] = f"{key_name}={key_value}\n"
                key_found = True
                break

    if not key_found:
        # 追加到末尾
        if existing_lines and not existing_lines[-1].endswith("\n"):
            existing_lines.append("\n")
        existing_lines.append(f"\n# 由 key_setup.py 于首次运行时写入\n{key_name}={key_value}\n")

    with open(env_path, "w", encoding="utf-8") as f:
        f.writelines(existing_lines)


def _prompt_single_key(key_name, apply_url, description):
    """交互式引导用户输入单个 Key。返回用户输入的 Key 字符串（可能为空）。"""
    print(f"\n{'=' * 60}", file=sys.stderr)
    print(f"检测到 {key_name} 未配置", file=sys.stderr)
    print(f"用途：{description}", file=sys.stderr)
    if apply_url:
        print(f"申请地址：{apply_url}", file=sys.stderr)
    print(f"{'=' * 60}", file=sys.stderr)
    print(f"请粘贴你的 {key_name}（直接回车跳过，稍后手动配置 .env）：", file=sys.stderr)
    try:
        user_input = input("> ").strip()
    except (EOFError, KeyboardInterrupt):
        print("\n已取消配置。", file=sys.stderr)
        return ""

    # 简单清洗：去首尾空白，去可能的引号
    if user_input.startswith('"') and user_input.endswith('"'):
        user_input = user_input[1:-1]
    elif user_input.startswith("'") and user_input.endswith("'"):
        user_input = user_input[1:-1]

    return user_input


def ensure_scp_key(silent=False):
    """确保 SCP_HUB_API_KEY 已配置。未配置时交互式引导用户输入。

    参数：
        silent: True 时不交互（用于非交互环境，直接返回空串）

    返回：
        SCP_HUB_API_KEY 字符串。用户已配置则返回真实值；未配置且拒绝输入则返回空串。
    """
    # 1. 先查 os.environ（shell 已 export 或 _load_dotenv 已加载）
    api_key = os.environ.get("SCP_HUB_API_KEY", "").strip()
    if api_key:
        return api_key

    # 2. Key 缺失，准备交互式引导
    if silent:
        # 非交互环境（如管道、CI）：只打印提示，不阻塞
        print(
            "WARNING: SCP_HUB_API_KEY not set. "
            "Copy .env.example to .env and fill in your key, "
            "or run this script interactively to configure.",
            file=sys.stderr,
        )
        return ""

    # 3. 检查是否有 .env.example 模板（提示用户可以参考）
    example_path = _find_example_file()
    env_path = _find_env_file()

    # 4. 交互式引导
    apply_url, description = REQUIRED_KEYS["SCP_HUB_API_KEY"]
    user_input = _prompt_single_key("SCP_HUB_API_KEY", apply_url, description)

    if not user_input:
        # 用户跳过
        print(
            "已跳过配置。脚本将以 mock 模式运行（返回模拟数据，不计入有效证据）。\n"
            "稍后可手动复制 .env.example 为 .env 并填入 Key，"
            "或重新运行本脚本。",
            file=sys.stderr,
        )
        return ""

    # 5. 写入 .env 文件
    try:
        _append_to_env_file(env_path, "SCP_HUB_API_KEY", user_input)
        # 同步到 os.environ，供本次运行直接使用
        os.environ["SCP_HUB_API_KEY"] = user_input
        print(f"\n已保存到 {env_path}", file=sys.stderr)
        print("后续运行无需再次配置。", file=sys.stderr)
        return user_input
    except Exception as e:
        print(f"写入 .env 失败：{e}", file=sys.stderr)
        print(f"请手动编辑 {env_path} 添加：SCP_HUB_API_KEY={user_input}", file=sys.stderr)
        # 仍同步到 os.environ 供本次运行使用
        os.environ["SCP_HUB_API_KEY"] = user_input
        return user_input


def check_key_status():
    """检查所有必填/可选 Key 的配置状态，返回状态字典。供诊断命令使用。"""
    status = {"required": {}, "optional": {}, "env_file": None, "example_file": None}

    for key in REQUIRED_KEYS:
        val = os.environ.get(key, "").strip()
        status["required"][key] = {
            "configured": bool(val),
            "masked": f"{val[:6]}...{val[-4:]}" if len(val) > 10 else "(空)" if not val else "(过短)",
        }

    for key in OPTIONAL_KEYS:
        val = os.environ.get(key, "").strip()
        status["optional"][key] = {
            "configured": bool(val),
            "masked": f"{val[:6]}...{val[-4:]}" if len(val) > 10 else "(空)" if not val else "(过短)",
        }

    status["env_file"] = str(_find_env_file()) if _find_env_file().exists() else None
    status["example_file"] = str(_find_example_file()) if _find_example_file() else None
    return status


def main():
    """诊断命令：打印 Key 配置状态。用法：python scripts/key_setup.py --status"""
    # 加载 .env 文件（与 search_papers.py / scp_tools.py 保持一致）
    _load_dotenv_self()
    import argparse
    parser = argparse.ArgumentParser(description="InterSci-KD API Key 配置与诊断")
    parser.add_argument("--status", action="store_true", help="打印所有 Key 的配置状态")
    parser.add_argument("--setup", action="store_true", help="交互式配置 SCP_HUB_API_KEY")
    args = parser.parse_args()

    if args.status:
        s = check_key_status()
        print(f"\n.env 文件：{s['env_file'] or '未找到'}")
        print(f".env.example 模板：{s['example_file'] or '未找到'}")
        print("\n必填 Key：")
        for k, v in s["required"].items():
            mark = "✅" if v["configured"] else "❌"
            print(f"  {mark} {k}: {v['masked']}")
        print("\n可选 Key：")
        for k, v in s["optional"].items():
            mark = "✅" if v["configured"] else "⚪"
            print(f"  {mark} {k}: {v['masked']}")
        return

    else:  # 默认走 setup 流程（--status 已在上面 return，其余情况都进 setup）
        key = ensure_scp_key()
        if key:
            print("\n配置完成。", file=sys.stderr)
        else:
            print("\n未配置，脚本将以 mock 模式运行。", file=sys.stderr)


if __name__ == "__main__":
    main()
