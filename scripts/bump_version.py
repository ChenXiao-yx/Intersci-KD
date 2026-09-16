#!/usr/bin/env python3
"""版本号一键 bump 工具（第八点评建议 5：版本残留从"靠人记"变成"不可能发生"）。

四处版本号单一事实源，本工具一次改齐：
  1. SKILL.md frontmatter        version: "X.Y.Z-skill"
  2. pyproject.toml              version = "X.Y.Z"
  3. CHANGELOG.md 尾行           **当前版本：X.Y.Z-skill**
  4. scripts/providers/base.py   UA = "InterSci-KD/X.Y.Z (...)"
  5. scripts/citation_lookup.py  UA（两处，v4.9.0 起纳入，修漂移）

用法：
    python scripts/bump_version.py                 # 只读报告（四处当前版本 + 是否统一）
    python scripts/bump_version.py 4.8.0 --check   # 只报告，不写入
    python scripts/bump_version.py 4.8.0           # 写入四处并自动跑 check_consistency

注意：CHANGELOG 的新版本修订条目（vX.Y.Z 段落）仍需人工追加——本工具只保证
"当前版本"尾行与四处一致，不代写修订内容。
"""
from __future__ import annotations
import argparse
import re
import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_SCRIPTS = Path(__file__).resolve().parent

TARGETS = [
    ("SKILL.md",
     r'(?m)^(version:\s*")([\d.]+)(-skill")',
     "SKILL.md frontmatter version"),
    ("pyproject.toml",
     r'(?m)^(version\s*=\s*")([\d.]+)(")',
     "pyproject.toml version"),
    ("CHANGELOG.md",
     r"(\*\*当前版本[:：]\s*\*{0,2})([\d.]+)(-skill\*{0,2})",
     "CHANGELOG 当前版本尾行"),
    ("scripts/providers/base.py",
     r"(InterSci-KD/)([\d.]+)",
     "providers/base.py UA"),
    ("scripts/citation_lookup.py",
     r"(InterSci-KD/)([\d.]+)",
     "citation_lookup.py UA（两处一次改齐）"),
]


def current_versions():
    found = []
    for rel, pattern, label in TARGETS:
        text = (_ROOT / rel).read_text(encoding="utf-8")
        m = re.search(pattern, text)
        found.append((rel, label, m.group(2) if m else None))
    return found


def bump(new_version):
    changed = []
    for rel, pattern, label in TARGETS:
        path = _ROOT / rel
        text = path.read_text(encoding="utf-8")
        new_text, n = re.subn(
            pattern,
            lambda m: m.group(1) + new_version + (m.group(3) if m.re.groups >= 3 else ""),
            text,
        )
        if n == 0:
            print(f"FAIL: {label} 未匹配到版本号模式", file=sys.stderr)
            return False
        path.write_text(new_text, encoding="utf-8")
        changed.append(f"{label} -> {new_version}")
    for c in changed:
        print(f"OK: {c}")
    return True


def main():
    parser = argparse.ArgumentParser(description="InterSci-KD 版本号一键 bump（四处一次改齐）")
    parser.add_argument("version", nargs="?", default=None,
                        help="新版本号，如 4.8.0；省略则只读报告")
    parser.add_argument("--check", action="store_true", help="只报告，不写入")
    args = parser.parse_args()

    found = current_versions()
    for rel, label, ver in found:
        print(f"{label}: {ver}")
    versions = {v for _, _, v in found}
    if None in versions:
        print("FAIL: 存在未解析到版本号的位置", file=sys.stderr)
        return 1
    if len(versions) > 1:
        print(f"WARN: 当前四处版本不统一: {sorted(versions)}", file=sys.stderr)

    if args.check:
        return 0
    if not args.version:
        print("（未传版本号：只读报告模式）")
        return 0

    if not re.fullmatch(r"\d+\.\d+\.\d+", args.version):
        print(f"FAIL: 版本号格式应为 X.Y.Z，收到 {args.version!r}", file=sys.stderr)
        return 1
    if not bump(args.version):
        return 1

    print("—— 自动运行一致性检查 ——")
    return subprocess.call([sys.executable, str(_SCRIPTS / "check_consistency.py")])


if __name__ == "__main__":
    sys.exit(main())
