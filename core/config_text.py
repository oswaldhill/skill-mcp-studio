"""config.yaml 文本级改写（保注释、不重排）—— scan.py 抽取（v0.30.0）。

为什么独立成模块：``--set-setting`` / ``--set-hook-template`` /
``--apply-hook-preset`` 与 v0.30.0 的 ``--import-config`` 共用同一套
text-rewrite 通道（改值不重排、注释全保留）。此前住在 scan.py，core 层的
config_porter 无法复用（core 不 import 入口脚本），故抽出（同 B 轨把
``_find_in_dict`` 等抽到 config_codec 的先例）。

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
    diff 最小，也与仓库既有的 `hooks.events:` 写法一致。
    返回多行时由 `_set_setting_in_text` 按多行插入（见那里的处理）。
    """
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, (list, tuple)):
        # 空列表必须显式写成 `[]`：若返回空串，调用方会按「单值」写成 `key: `
        # （空值）—— 既不是列表语义，也**不会触发旧块序列行的清理**（实测清空
        # hook_events 时旧元素残留）。
        if not value:
            return "[]"
        return "\n".join(f"- {item}" for item in value)
    return str(value)


def _find_client_template_span(raw: str, client_name: str):
    """在 config.yaml 的 ``hooks.clients`` 段内定位 ``[client_name].template`` 块。

    返回 ``(tpl_line_idx, block_end_idx, current_dict)`` 或 None。
    必须限定在 hooks 段（mcp_tools 段也有 ``- name:`` 会误匹配）。
    """
    import re as _re
    lines = raw.splitlines()
    pat_hooks = _re.compile(r"^hooks:\s*$")
    pat_top = _re.compile(r"^[a-zA-Z]")  # 下一个顶层 key（结束 hooks 段）
    pat_clients = _re.compile(r"^  clients:\s*$")
    pat_name = _re.compile(r"^  - name:\s+(.+?)\s*$")
    pat_tpl_inline = _re.compile(r"^    template:\s*\{\}\s*(#.*)?$")
    pat_tpl_block = _re.compile(r"^    template:\s*$")
    pat_entry = _re.compile(r"^        (.+?):\s*(.*?)\s*$")
    n = len(lines)
    # 1. 定位 hooks: 段
    i = 0
    while i < n and not pat_hooks.match(lines[i]):
        i += 1
    if i >= n:
        return None  # 无 hooks 段
    i += 1
    # 2. 在 hooks 段内找 clients:
    while i < n:
        if pat_top.match(lines[i]):
            return None  # 离开 hooks 段
        if pat_clients.match(lines[i]):
            break
        i += 1
    else:
        return None  # 无 clients 段
    i += 1
    # 3. 在 clients 列表里找 - name: <client_name>
    while i < n:
        if pat_top.match(lines[i]) or (lines[i].startswith("  - name:") is False and lines[i].startswith("    ") is False and lines[i].strip() and not lines[i].startswith(" ")):
            break  # 离开 clients 段
        m = pat_name.match(lines[i])
        if m and m.group(1).strip() == client_name:
            # 4. 在该客户端块内找 template:
            j = i + 1
            while j < n:
                if pat_name.match(lines[j]):
                    return None  # 下一个客户端，本块无 template
                if pat_tpl_inline.match(lines[j]):
                    return (j, j + 1, {})
                if pat_tpl_block.match(lines[j]):
                    k = j + 1
                    cur = {}
                    while k < n:
                        em = pat_entry.match(lines[k])
                        if em:
                            cur[em.group(1)] = em.group(2)
                            k += 1
                            continue
                        break
                    return (j, k, cur)
                j += 1
            return None
        i += 1
    return None


def _render_template_block(template: dict) -> list:
    """渲染 template 块行（不含尾换行）。空 dict → inline ``{}``。"""
    if not template:
        return ["    template: {}"]
    lines = ["    template:"]
    for ev, cmd in template.items():
        lines.append(f"        {ev}: {cmd}")
    return lines


def _rewrite_client_template(raw: str, client_name: str, new_template: dict) -> str:
    """text-rewrite：替换 hooks.clients[client_name] 的 template 块为 new_template。

    保留其余所有行/注释（同 _set_setting_in_text 保注释理由）。
    """
    span = _find_client_template_span(raw, client_name)
    if span is None:
        raise ValueError(f"未在 hooks.clients 找到客户端「{client_name}」或其 template 段")
    tpl_idx, end_idx, _cur = span
    lines = raw.splitlines(keepends=True)
    # 计算字节偏移（lines[k] 含尾换行）
    start_off = sum(len(lines[k]) for k in range(tpl_idx))
    end_off = sum(len(lines[k]) for k in range(end_idx))
    new_lines = _render_template_block(new_template)
    rendered = "".join(ln + "\n" for ln in new_lines)
    # 若原块末行无尾换行（EOF），去掉 rendered 末尾换行以对齐
    if end_off <= len(raw) and (end_off == len(raw) or raw[end_off] == "\n") is False and not lines[end_idx - 1].endswith("\n"):
        rendered = rendered.rstrip("\n")
    return raw[:start_off] + rendered + raw[end_off:]


def _set_default_command_in_text(raw: str, command: str) -> str:
    """在 config.yaml 的 ``hooks:`` 段内改写 ``default_command`` 的值，保留行尾注释。

    与 ``_set_setting_in_text`` 同属文本级改写（保注释、不重排），但定位 ``hooks:``
    段而非 ``settings:``，且只替换值部分（``default_command: "<old>"`` →
    ``default_command: "<new>"``），行尾 ``# ...`` 注释原样保留。

    v0.30.0 加固（config_porter 导入路径暴露）：旧正则只认**双引号**值——
    单引号（``''``）或裸值风格的行会**静默不匹配**（sub 无效果、返回原文）。
    现支持双引号 / 单引号 / 裸值三种既有风格；新值统一用 ``json.dumps``
    渲染（JSON 双引号字符串是 YAML 双引号字符串的子集，命令内含引号也能
    正确转义）。
    """
    import json as _json
    import re as _re
    lines = raw.split("\n")
    # 1. 定位 hooks: 段
    sec_start = None
    for i, line in enumerate(lines):
        if line.rstrip() == "hooks:" or line.rstrip().startswith("hooks:"):
            sec_start = i
            break
    if sec_start is None:
        raise ValueError("config.yaml 无 hooks: 段")
    # 2. 段范围：到下一个顶格行
    sec_end = len(lines)
    for j in range(sec_start + 1, len(lines)):
        line = lines[j]
        if line and not line[0].isspace() and not line.lstrip().startswith("#"):
            sec_end = j
            break
    # 3. 找 default_command: 行（2-space 缩进）
    target = None
    for j in range(sec_start + 1, sec_end):
        if lines[j].lstrip().startswith("default_command:"):
            target = j
            break
    if target is None:
        raise ValueError("hooks: 段内无 default_command 字段")
    # 4. 替换值部分（保留行尾注释）：default_command: "<old>"  # ...
    #    值部分匹配三种风格：双引号 / 单引号 / 裸值（到行尾注释前）。
    old_line = lines[target]
    new_line = _re.sub(
        r"(default_command:\s*)(?:\"[^\"]*\"|'[^']*'|[^#\n]*?)(\s*(?:#.*)?)$",
        lambda m: f'{m.group(1)}{_json.dumps(command)}{m.group(2)}',
        old_line,
        count=1,
    )
    lines[target] = new_line
    return "\n".join(lines)
