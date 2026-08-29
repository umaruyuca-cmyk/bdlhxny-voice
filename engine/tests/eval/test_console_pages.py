"""公开站点与真源同步守卫(两类实验口径)。

- 工具构成页(/engine/tools)以聚合口径展示目录构成(通用/领域/元工具)——
  数量须与工具目录一致,逐名列举改为构成校验(页面不维护第二份全名单);
- 用例库页(/cases)由 catalog.js 读取 cases.json 公开投影渲染,
  不硬编码题号,公开投影不含评判配置(由 web 侧 site-structure 测试守卫);
- 旧实证结果页(/showcase/results)收敛为公告页跳转;公告页只读正式发布索引
  publications/index.json,未发布统一显示「尚未发布」。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

_WEB_PUBLIC = Path(__file__).resolve().parents[3] / "web" / "public"


def test_tools_page_lists_all_catalog_tools():
    """工具构成页:独立构成页已并入工具目录页(跳转桩),目录页声明构成明细。"""
    html = (_WEB_PUBLIC / "engine" / "tools.html").read_text(encoding="utf-8")
    if "已并入" in html:  # 跳转桩:内容并入 /tools/ 目录页,构成断言移至目录页
        target = (_WEB_PUBLIC / "tools" / "index.html").read_text(encoding="utf-8")
        assert "112" in target, "工具目录页需声明目录总量 112"
        assert "search_tools" in target or "检索" in target, "检索元工具需在目录页说明"
        return
    assert "112" in html, "构成页需声明目录总量 112"
    assert "96" in html and "16" in html, "构成页需声明 通用96/领域16 两档数量"
    assert "search_tools" in html, "检索元工具需在构成页说明"
    assert "快照" in html, "构成页需声明为目录快照投影(真源在数据库)"


def test_cases_page_is_data_driven_not_hardcoded():
    """用例库页由目录脚本渲染公开投影,不得出现题号字面量或旧类别。"""
    html = (_WEB_PUBLIC / "cases" / "index.html").read_text(encoding="utf-8")
    assert "catalog.js" in html, "用例库页由目录脚本渲染"
    assert not re.search(r"cmp-[a-z]+-\d+", html), "用例库页不得硬编码题号表格"
    for legacy_kind in ("generic", "negative", "复杂多工具"):
        assert legacy_kind not in html, f"用例库页不得保留旧类别口径:{legacy_kind}"
    # 旧 ctx-* 长上下文用例类别不得回流用例库(模块名「长上下文库」的指引除外)
    assert 'value="context"' not in html, "用例库不得保留 ctx 长上下文类别筛选项"


def test_results_page_redirects_to_announce():
    """旧实证结果页只保留跳转;批次汇总收敛到公告页。"""
    html = (_WEB_PUBLIC / "showcase" / "results.html").read_text(encoding="utf-8")
    assert 'http-equiv="refresh"' in html
    assert "/#dashboard" in html or "公告" in html


def test_announce_reads_publication_index_only():
    """公告页空框架:只读正式发布索引;不读旧批次索引/调试产物。"""
    html = (_WEB_PUBLIC / "index.html").read_text(encoding="utf-8")
    assert "publications/index.json" in html, "公告页只读正式发布索引"
    assert "showcase-data/index.json" not in html, "公告页不读旧批次索引"
    assert "showcase-data/batches/" not in html, "公告页不加载批次产物"
    assert "尚未发布" in html, "未发布时统一显示「尚未发布」空状态"
    publications = json.loads(
        (_WEB_PUBLIC / "showcase-data" / "publications" / "index.json").read_text(encoding="utf-8")
    )
    assert publications.get("formal_publications") == [], "正式发布索引初始为空(本任务不生成公告数据)"


def test_judging_metrics_page_is_pure_definitions():
    """指标定义总表:纯文档,不读批次数据;数字入口指向公告页(跳转桩同样合规)。"""
    html = (_WEB_PUBLIC / "judging" / "metrics.html").read_text(encoding="utf-8")
    assert "fetch(" not in html, "指标定义页不得发起数据请求"
    assert "batches/" not in html, "指标定义页不得引用批次产物"
    assert "showcase-data/index.json" not in html, "指标定义页不得读旧批次索引"
    if "已并入" not in html:  # 独立总表页保留时才检查入口文案;跳转桩无正文
        assert "公告页" in html, "指标数字入口指向公告页"


def test_context_results_reads_publication_index_only():
    """上下文结果页:只读正式发布索引;未发布时空状态。"""
    html = (_WEB_PUBLIC / "context" / "results.html").read_text(encoding="utf-8")
    assert "publications/index.json" in html
    assert "showcase-data/index.json" not in html
    assert "showcase-data/batches/" not in html
    assert "尚未发布" in html


def test_compression_experiment_page_links_library_for_details():
    """压缩实验页:概览+选中,压缩前后明细唯一展示在长上下文库。"""
    html = (_WEB_PUBLIC / "experiment" / "compression.html").read_text(encoding="utf-8")
    assert "压缩前 Token</th>" not in html, "实验页不再渲染压缩前后明细表"
    assert "/context/library" in html, "实验页需链接长上下文库查看完整对照"
    assert "data-select-session" in html
