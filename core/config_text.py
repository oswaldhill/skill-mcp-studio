"""config.yaml 文本级改写（保注释、不重排）—— scan.py 抽取（v0.30.0）。

为什么独立成模块：``--set-setting`` 与 v0.30.0 的 ``--import-config``
共用同一套 text-rewrite 通道（改值不重排、注释全保留）。此前住在 scan.py，
core 层的 config_porter 无法复用（core 不 import 入口脚本），故抽出（同 B
轨把 ``_find_in_dict`` 等抽到 config_codec 的先例）。

函数名保留下划线前缀（与 config_codec._find_in_dict 惯例一致）；
scan.py 以 ``from config_text import ...`` 别名引用，调用点与既有测试
（tests/test_set_setting_text_write.py 经 scan 模块访问）零改动。
"""

def _set_setting_in_text(raw: str, key: str, value) -> str:
    """在 config.yaml 原文里改写 settings 段的单个键，**保留其余文本原样**。

    为什么不用 yaml.safe_load + safe_dump：那会重新序列化整份文件 —— 内联数组
    被拆成多行、所有注释被抹掉。实测改一个布尔值产生 383 行 diff，50 行注释
    全部丢失，等于每次改设置都毁掉配置里的文档。

    规则（面向本仓库 config.yaml 的实际形态，settings 是最后一个顶层键）：
    - 已存在 `settings:` 段：只替换其中该键的整行，其余行一字不动；
      键不存在则在段内追加一行。
    - 没有 `settings:` 段：在文件末尾追加一个 `settings:` 段。
    - 行尾换行保持「恰好一个」。
    """
    lines = raw.split("\n")
    # 去掉末尾空元素以便处理，最后再补回换行
    trailing_newline = raw.endswith("\n")
    if trailing_newline and lines and lines[-1] == "":
        lines.pop()

    rendered = _render_scalar(value)
    sec_start = None
    for i, line in enumerate(lines):
        if line.rstrip() == "settings:" or line.rstrip().startswith("settings:"):
            sec_start = i
            break

    if sec_start is None:
        # 末尾追加新段
        lines.append("settings:")
        if "\n" in rendered or rendered == "[]":
            lines.append(f"  {key}: []" if rendered == "[]" else f"  {key}:")
            if rendered != "[]":
                lines.extend(f"  {ln}" for ln in rendered.split("\n") if ln != "")
        else:
            lines.append(f"  {key}: {rendered}")
    else:
        # 段范围：到下一个顶格行（非缩进、非空、非注释）为止
        sec_end = len(lines)
        for j in range(sec_start + 1, len(lines)):
            line = lines[j]
            if line and not line[0].isspace() and not line.lstrip().startswith("#"):
                sec_end = j
                break
        target = None
        for j in range(sec_start + 1, sec_end):
            stripped = lines[j].strip()
            if stripped.startswith(f"{key}:"):
                target = j
                break
        if target is not None:
            indent = lines[target][: len(lines[target]) - len(lines[target].lstrip())]
            if "\n" in rendered or rendered == "[]":
                block = [f"{indent}{key}: []" if rendered == "[]" else f"{indent}{key}:"]
                if rendered != "[]":
                    block += [f"{indent}{ln}" for ln in rendered.split("\n") if ln != ""]
                # 旧值若本来就是块序列，后续 `- item` 行必须一并删掉 ——
                # 否则它们会残留成新列表的尾巴（改成空列表时尤其明显）。
                end = target + 1
                while end < len(lines) and lines[end].lstrip().startswith("- "):
                    end += 1
                lines[target:end] = block
            else:
                lines[target] = f"{indent}{key}: {rendered}"
        else:
            if "\n" in rendered or rendered == "[]":
                block = [f"  {key}: []" if rendered == "[]" else f"  {key}:"]
                if rendered != "[]":
                    block += [f"  {ln}" for ln in rendered.split("\n") if ln != ""]
                lines[sec_end:sec_end] = block
            else:
                lines.insert(sec_end, f"  {key}: {rendered}")

    out = "\n".join(lines)
    # 统一以单个换行结尾（文本卫生要求「恰好一个」）
    return out + "\n"


def _render_scalar(value) -> str:
    """把设置值渲染成 YAML 标量（布尔用小写 true/false，与仓库既有写法一致）。

    列表走**块序列**（每行一个 `- item`）而不是内联 `[a, b]`：本函数与
    `_set_setting_in_text` 都是按行改写，块序列让「替换该键」的范围清晰、
    diff 最小。
    返回多行时由 `_set_setting_in_text` 按多行插入（见那里的处理）。
    """
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, (list, tuple)):
        # 空列表必须显式写成 `[]`：若返回空串，调用方会按「单值」写成 `key: `
        # （空值）—— 既不是列表语义，也**不会触发旧块序列行的清理**（实测把
        # 某列表键改为空时旧元素残留）。
        if not value:
            return "[]"
        return "\n".join(f"- {item}" for item in value)
    return str(value)
