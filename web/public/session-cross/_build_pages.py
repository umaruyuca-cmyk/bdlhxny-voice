"""生成 Session 交叉验证旧地址的兼容跳转页。

交叉验证已经合并到 index.html：原始 Session、四种上下文方式、压缩前后文本和
4×3 结果矩阵必须在同一页阅读。此脚本不生成数据、不执行实验，也不覆盖主页面。
"""

from pathlib import Path


ROOT = Path(__file__).resolve().parent


def redirect_page(title: str, anchor: str, description: str) -> str:
    target = f"/session-cross/#{anchor}"
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="refresh" content="0;url={target}">
<title>{title} · Session 交叉验证</title>
<meta name="description" content="{description}">
<link rel="canonical" href="{target}">
</head>
<body>
<p>交叉验证内容已合并到单页框架。<a href="{target}">继续查看 {title}</a>。</p>
</body>
</html>
"""


def main() -> None:
    pages = {
        "inputs.html": redirect_page(
            "压缩前后",
            "comparison",
            "原始 Session 与四种上下文处理后模型输入的同页对照。",
        ),
        "results.html": redirect_page(
            "交叉验证结果",
            "matrix",
            "四种上下文方式与三种 Agent 实现的 4×3 结果矩阵。",
        ),
    }
    for name, content in pages.items():
        (ROOT / name).write_text(content, encoding="utf-8")


if __name__ == "__main__":
    main()
