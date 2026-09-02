"""公开站点与真源同步守卫(信息架构 v3 · 五页)。

- 首页系统构成事实卡与 showcase-data 静态数据一致(不以构成数字冒充成绩);
- 测试逻辑页(/methodology/)的实验清单与引擎模板注册表同步(真源在 templates.py);
- 结果/证据两核心页只读发布器公开快照(经统一适配层),未发布保持空状态;
- 正式发布索引为空属预期(本任务不生成正式数据)。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

_WEB_PUBLIC = Path(__file__).resolve().parents[3] / "web" / "public"
_ENGINE_SRC = Path(__file__).resolve().parents[2] / "src" / "bdlh_runtime"


def test_home_composition_facts_match_data_sources():
    """首页系统构成事实卡:数量与 tools.json / cases.json / context-library.json 一致。"""
    html = (_WEB_PUBLIC / "index.html").read_text(encoding="utf-8")
    nums = [int(n) for n in re.findall(r'<div class="fact"><b>(\d+)</b>', html)]
    assert len(nums) == 4, "首页应有四张构成事实卡"
    tools = json.loads((_WEB_PUBLIC / "showcase-data" / "tools.json").read_text(encoding="utf-8"))
    cases = json.loads((_WEB_PUBLIC / "showcase-data" / "cases.json").read_text(encoding="utf-8"))
    library = json.loads(
        (_WEB_PUBLIC / "showcase-data" / "context-library.json").read_text(encoding="utf-8")
    )
    assert nums[0] == tools["total"], "工具数与 tools.json 一致"
    assert nums[1] == cases["total"], "对比用例数与 cases.json 一致"
    assert nums[2] == len(library["entries"]), "Session 数与 context-library.json 一致"
    # 构成事实明确标注为非实验成绩
    assert "非实验成绩" in html, "构成事实卡必须声明非实验成绩"


def test_methodology_template_list_syncs_engine_registry():
    """测试逻辑页实验清单:逐项包含引擎注册的全部模板 ID(真源 templates.py)。"""
    html = (_WEB_PUBLIC / "methodology" / "index.html").read_text(encoding="utf-8")
    registry = (_ENGINE_SRC / "experiments" / "templates.py").read_text(encoding="utf-8")
    registered = sorted(set(re.findall(r'template_id="([a-z0-9-]+)"', registry)))
    assert registered, "引擎模板注册表非空"
    for template_id in registered:
        assert template_id in html, f"测试逻辑页缺少模板 {template_id}"
    assert "模板存在不代表已有正式结果" in html, "区分模板存在与已有正式结果"


def test_results_and_evidence_read_publisher_snapshot_only():
    """两核心页只读发布器公开快照;未发布保持真实空状态。"""
    results = (_WEB_PUBLIC / "results" / "index.html").read_text(encoding="utf-8")
    evidence = (_WEB_PUBLIC / "evidence" / "index.html").read_text(encoding="utf-8")
    for name, html in (("/results/", results), ("/evidence/", evidence)):
        assert "/api/v1/" not in html, f"{name} 不得出现后端 API"
        assert "fetch(" not in html, f"{name} 页面 HTML 不直接发起请求(统一经适配层)"
        assert "尚无正式" in html or "尚无公开" in html, f"{name} 未发布时空状态文案存在"
    adapter = (_WEB_PUBLIC / "docs" / "showcase-data.js").read_text(encoding="utf-8")
    for forbidden in ("/api/v1/", "sessionStorage", "localStorage"):
        assert forbidden not in adapter, f"适配层不得包含 {forbidden}"


def test_publication_indices_empty_until_formal_batch_published():
    """发布器索引与登记索引均为空(空状态真实,无手填成绩)。"""
    index = json.loads((_WEB_PUBLIC / "showcase-data" / "index.json").read_text(encoding="utf-8"))
    assert index.get("formal_batches") == [], "发布器索引初始为空"
    assert index.get("latest_batch") is None, "无最新批次时 latest_batch 为 null"
    publications = json.loads(
        (_WEB_PUBLIC / "showcase-data" / "publications" / "index.json").read_text(encoding="utf-8")
    )
    assert publications.get("formal_publications") == [], "发布登记索引初始为空"


def test_metric_definitions_single_source_on_methodology():
    """指标定义全站唯一版本在测试逻辑页;执行逻辑页只引用锚点,不复制表格。"""
    methodology = (_WEB_PUBLIC / "methodology" / "index.html").read_text(encoding="utf-8")
    assert 'id="metrics"' in methodology, "指标定义锚点在测试逻辑页"
    assert "全站唯一版本" in methodology
    system = (_WEB_PUBLIC / "system" / "index.html").read_text(encoding="utf-8")
    assert 'href="/methodology/#metrics"' in system, "执行逻辑页引用指标定义锚点"
    system_metrics_table = re.search(r"<h3[^>]*>指标定义.*?</h3>.*?</table>", system, re.S)
    assert system_metrics_table is None, "执行逻辑页不得复制指标定义表"
