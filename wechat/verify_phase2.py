# encoding:utf-8
"""Phase-2 客观自动验证（P1.6）。

目标：捕获 Claude "改完了" 但实际改炸的场景：
- 文件改完语法错（SyntaxError）
- import 链断了（ImportError / 循环依赖）
- 改完但未保存（mtime 没更新 → 我们也能发现）

设计原则：
1. **机械检查 > 让 Claude 自审**——Claude 撒过谎（acceptEdits 之前那次"改完了"磁盘没动）
2. **只看磁盘上的事实**——不解析 Claude 的输出文本
3. **失败不阻断**——verify 自己崩了不影响 phase-2 报告
4. **不打扰用户**——通过就一行 "✓ 验证通过 (N 个文件)"，不需要时不刷屏

不做：
- 语义对错（"Claude 改的是不是用户要的"）→ 那是人和 Claude 之间的事
- 跑测试（耗时太长，且不一定有相关 test 覆盖）
- 跑 lint（噪声大，会误报）
"""
from __future__ import annotations

import logging
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent

# 总预算（包括 py_compile + import）
VERIFY_TIMEOUT_TOTAL = 60
# 单文件 py_compile / import 超时
VERIFY_TIMEOUT_PER_CHECK = 15


def _run_git_status() -> set[str]:
    """跑 `git status --porcelain`，返回所有 dirty 文件路径集合。"""
    try:
        proc = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=str(_PROJECT_ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
            shell=False,
        )
    except Exception as e:
        logger.warning(f"[verify] git status failed: {e}")
        return set()
    if proc.returncode != 0:
        return set()
    paths = set()
    for line in proc.stdout.splitlines():
        if len(line) < 4:
            continue
        # 格式："XY path"（XY 是状态码，例如 " M" / "??" / "MM"）
        path = line[3:].strip()
        if path.startswith('"') and path.endswith('"'):
            path = path[1:-1]  # 引号路径
        if " -> " in path:
            path = path.split(" -> ", 1)[1]  # 重命名取新名
        paths.add(path)
    return paths


def snapshot_files_with_mtime() -> dict[str, float]:
    """snapshot 当前所有 dirty 文件 + mtime。

    返回 {相对路径: mtime}。如果 git 不可用，返回空 dict——后续 diff 视所有
    final 阶段的 dirty 文件都为"新"，仍然能验证。
    """
    paths = _run_git_status()
    out: dict[str, float] = {}
    for p in paths:
        full = _PROJECT_ROOT / p
        try:
            if full.exists():
                out[p] = full.stat().st_mtime
        except OSError:
            pass
    return out


def changed_files_since(baseline: dict[str, float]) -> list[str]:
    """对比当前 dirty 文件 vs baseline，返回 mtime 比 baseline 新或全新的文件。"""
    final_paths = _run_git_status()
    changed: list[str] = []
    for rel in final_paths:
        full = _PROJECT_ROOT / rel
        if not full.exists():
            continue  # 文件被删，不需要验证
        try:
            mtime = full.stat().st_mtime
        except OSError:
            continue
        baseline_mtime = baseline.get(rel, 0.0)
        # 允许微小浮点误差（同一秒内连续操作可能 mtime 相同）
        if mtime > baseline_mtime + 0.0001:
            changed.append(rel)
    changed.sort()
    return changed


def _path_to_module(rel_path: str) -> Optional[str]:
    """`wechat/dispatcher.py` → `wechat.dispatcher`；非 package 文件返回 None。"""
    if not rel_path.endswith(".py"):
        return None
    p = Path(rel_path).with_suffix("")
    parts = list(p.parts)
    if not parts:
        return None
    if parts[-1] == "__init__":
        # 把 foo/__init__.py 当作 foo 模块
        parts = parts[:-1]
        if not parts:
            return None
    # 检查从项目根到该文件每一级都有 __init__.py
    cur = _PROJECT_ROOT
    for part in parts[:-1]:
        cur = cur / part
        if not (cur / "__init__.py").exists():
            return None
    return ".".join(parts)


def verify_python_files(paths: list[str], deadline_at: float) -> dict:
    """对每个 .py 文件跑 py_compile + import 检查。

    deadline_at：epoch 秒，超过就提前停。
    返回 dict 详见 format_report。
    """
    result = {
        "syntax_ok": [],
        "syntax_fail": [],   # [(rel_path, err_msg)]
        "import_ok": [],     # [module_name]
        "import_fail": [],   # [(rel_path, err_msg)]
        "non_python_files": [],
        "skipped_budget": [],  # 超预算未跑的
    }
    for rel_path in paths:
        if time.time() >= deadline_at:
            result["skipped_budget"].append(rel_path)
            continue
        if not rel_path.endswith(".py"):
            result["non_python_files"].append(rel_path)
            continue
        full = _PROJECT_ROOT / rel_path
        if not full.exists():
            continue

        # 1. 语法检查
        try:
            proc = subprocess.run(
                [sys.executable, "-m", "py_compile", str(full)],
                cwd=str(_PROJECT_ROOT),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=VERIFY_TIMEOUT_PER_CHECK,
                shell=False,
            )
        except subprocess.TimeoutExpired:
            result["syntax_fail"].append((rel_path, "py_compile timeout"))
            continue
        except Exception as e:
            result["syntax_fail"].append((rel_path, f"py_compile crashed: {e}"))
            continue
        if proc.returncode != 0:
            err = (proc.stderr or proc.stdout or "(no output)").strip()
            result["syntax_fail"].append((rel_path, err[:300]))
            continue
        result["syntax_ok"].append(rel_path)

        # 2. import 检查（仅 package 文件）
        mod_name = _path_to_module(rel_path)
        if mod_name is None:
            continue
        if time.time() >= deadline_at:
            result["skipped_budget"].append(rel_path)
            continue
        try:
            proc = subprocess.run(
                [sys.executable, "-c", f"import {mod_name}"],
                cwd=str(_PROJECT_ROOT),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=VERIFY_TIMEOUT_PER_CHECK,
                shell=False,
            )
        except subprocess.TimeoutExpired:
            result["import_fail"].append((rel_path, "import timeout"))
            continue
        except Exception as e:
            result["import_fail"].append((rel_path, f"import crashed: {e}"))
            continue
        if proc.returncode != 0:
            err = (proc.stderr or proc.stdout or "(no output)").strip()
            result["import_fail"].append((rel_path, err[:300]))
        else:
            result["import_ok"].append(mod_name)

    return result


def _summarize_python_error(err: str) -> str:
    """从 py_compile / import 的多行报错里提炼出最有用的一行。

    Python 的 SyntaxError / ImportError 关键信息通常在最后一行（如
    `SyntaxError: '(' was never closed`）。File path 行没用、source 行也没用。
    """
    # 找最后一个看起来像 "ErrorType: detail" 的行
    for line in reversed(err.strip().split("\n")):
        line = line.strip()
        if not line:
            continue
        # 优先取带 "Error:" / "Exception:" 的行
        if ":" in line and any(kw in line for kw in (
            "Error", "Exception", "Warning", "Traceback"
        )):
            return line[:150]
    # 兜底：最后一非空行
    nonempty = [l.strip() for l in err.strip().split("\n") if l.strip()]
    return (nonempty[-1] if nonempty else err[:150])[:150]


def format_report(changed: list[str], r: dict) -> tuple[bool, str]:
    """生成人类可读的验证报告。返回 (all_ok, message)。"""
    if not changed:
        return True, "🔍 自动验证：本次未检测到文件变化（Claude 可能只读了文件，未实际修改）"

    has_failure = bool(r["syntax_fail"] or r["import_fail"])
    py_changed = [p for p in changed if p.endswith(".py")]
    py_total = len(py_changed)

    lines = ["🔍 自动验证："]

    # 语法
    if r["syntax_fail"]:
        lines.append(f"  ✗ 语法错误 ({len(r['syntax_fail'])} 个)：")
        for path, err in r["syntax_fail"][:3]:
            err_summary = _summarize_python_error(err)
            lines.append(f"    - {path}")
            lines.append(f"      {err_summary}")
        if len(r["syntax_fail"]) > 3:
            lines.append(f"    ...还有 {len(r['syntax_fail']) - 3} 个未列出")
    elif r["syntax_ok"]:
        lines.append(f"  ✓ 语法 OK ({len(r['syntax_ok'])} 个 .py)")

    # Import
    if r["import_fail"]:
        lines.append(f"  ✗ Import 失败 ({len(r['import_fail'])} 个)：")
        for path, err in r["import_fail"][:3]:
            err_summary = _summarize_python_error(err)
            lines.append(f"    - {path}")
            lines.append(f"      {err_summary}")
    elif r["import_ok"]:
        mods_preview = ", ".join(r["import_ok"][:3])
        if len(r["import_ok"]) > 3:
            mods_preview += f" ...等 {len(r['import_ok'])} 个"
        lines.append(f"  ✓ Import OK ({mods_preview})")

    # 其他文件提示
    non_py = r["non_python_files"]
    if non_py:
        if len(non_py) == 1:
            lines.append(f"  · {non_py[0]} 已改但非 Python，未自动验证")
        else:
            lines.append(f"  · 其他 {len(non_py)} 个非 .py 文件已改，未自动验证")

    if r["skipped_budget"]:
        lines.append(f"  · {len(r['skipped_budget'])} 个文件因超预算未验证")

    if has_failure:
        lines.append("")
        lines.append("⚠️ 处理建议：")
        lines.append("  1. 自己看错误信息修复（VS Code 里可直接看 git diff）")
        lines.append("  2. 或重新触发：@claude 修一下刚才的验证错误")
        lines.append("  3. 修复后再发『重启』生效")

    return not has_failure, "\n".join(lines)


def run_verify(baseline: dict[str, float]) -> tuple[bool, str]:
    """顶层入口：对比 baseline，跑验证，返回 (all_ok, report_message)。

    全程 try/except 兜底——verify 自己挂掉也不影响 phase-2 报告。
    """
    try:
        t0 = time.time()
        changed = changed_files_since(baseline)
        if not changed:
            return True, "🔍 自动验证：未检测到文件变化"
        deadline = t0 + VERIFY_TIMEOUT_TOTAL
        verify_result = verify_python_files(changed, deadline)
        return format_report(changed, verify_result)
    except Exception as e:
        logger.exception(f"[verify] run_verify crashed: {e}")
        return True, f"🔍 自动验证未运行（{type(e).__name__}: {str(e)[:80]}）——请手动检查"
