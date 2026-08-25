from __future__ import annotations

import math
import os
import unicodedata
from pathlib import Path
from typing import Protocol

#: 计数口径版本:CJK/标点每字 1 token,拉丁字母/数字每 4 字符 1 token。
#: 写入工件与上下文处理报告(tokenizer_version),保证口径可辨。
CONSERVATIVE_TOKENIZER_VERSION = "conservative-cjk1-latin4-v1"

#: tiktoken 精确口径(cl100k_base 词表;对 Qwen 为通用近似口径)
TIKTOKEN_TOKENIZER_VERSION = "tiktoken-cl100k-base-v1"

#: Qwen 官方词表精确口径(qwen.tiktoken,151,643 基础词元)
QWEN_TIKTOKEN_VERSION = "tiktoken-qwen-v1"

#: Qwen 词表默认缓存位置(--init-qwen 下载到此;可用 QWEN_TIKTOKEN_FILE 覆盖)
_DEFAULT_QWEN_VOCAB = Path(__file__).resolve().parents[3] / "var" / "cache" / "qwen.tiktoken"

#: 词表下载源(hf-mirror 对国内直连友好;官方源 huggingface.co/Qwen/Qwen-7B)
_DEFAULT_QWEN_VOCAB_URL = "https://hf-mirror.com/Qwen/Qwen-7B/resolve/main/qwen.tiktoken"


class TokenCounter(Protocol):
    def count(self, text: str) -> int: ...


class ConservativeTokenCounter:
    """Deterministic fallback used when a model tokenizer is unavailable."""

    def count(self, text: str) -> int:
        if not text:
            return 0

        cjk_or_symbol = 0
        latin_or_number = 0
        for character in text:
            if character.isspace():
                continue
            name = unicodedata.name(character, "")
            if (
                "CJK" in name
                or "HIRAGANA" in name
                or "KATAKANA" in name
                or "HANGUL" in name
                or unicodedata.category(character).startswith("P")
            ):
                cjk_or_symbol += 1
            else:
                latin_or_number += 1

        return cjk_or_symbol + math.ceil(latin_or_number / 4)


class TiktokenCounter:
    """tiktoken(cl100k_base)精确计数;预算口径随 tokenizer_version 冻结。

    说明:cl100k_base 是 OpenAI 词表,对 Qwen 只是通用近似——
    中文一般每字 0.6~1 token,通常低于保守口径。启用后同一预算能容纳
    更多内容,工件中的 tokenizer_version 会相应变化,跨批次不可混比。
    """

    def __init__(self) -> None:
        import tiktoken

        self._encoding = tiktoken.get_encoding("cl100k_base")

    def count(self, text: str) -> int:
        if not text:
            return 0
        return len(self._encoding.encode(text))


class QwenTiktokenCounter:
    """Qwen 官方 BPE 词表(tiktoken 格式)精确计数。

    词表取自 Qwen 官方发布的 ``qwen.tiktoken``(151,643 个基础词元,
    Qwen 系列同源;若所用模型带扩展词表,计数会有小幅偏差,但远小于
    保守口径的偏差)。切分模式与 cl100k 相同,差异只在词元表。

    词表文件是本地依赖(零网络、确定性):默认缓存于
    ``engine/var/cache/qwen.tiktoken``,可用环境变量 ``QWEN_TIKTOKEN_FILE``
    指定其他路径;文件缺失直接报错并给出初始化命令,不静默换口径:
    ``python -m bdlh_runtime.context.token_count --init-qwen``
    """

    #: Qwen 官方 tokenization 的特殊词元(与基础词表衔接)
    _SPECIAL_TOKENS = {
        "<|endoftext|>": 151643,
        "<|im_start|>": 151644,
        "<|im_end|>": 151645,
    }

    def __init__(self, vocab_path: str | os.PathLike[str] | None = None) -> None:
        import tiktoken
        from tiktoken.load import load_tiktoken_bpe

        path = Path(vocab_path or os.getenv("QWEN_TIKTOKEN_FILE") or _DEFAULT_QWEN_VOCAB)
        if not path.is_file():
            raise FileNotFoundError(
                f"Qwen 词表文件缺失:{path}。"
                "先执行 python -m bdlh_runtime.context.token_count --init-qwen 下载到本地缓存"
                "(或用环境变量 QWEN_TIKTOKEN_FILE 指定已有词表路径)。"
            )
        mergeable_ranks = load_tiktoken_bpe(str(path))
        self._encoding = tiktoken.Encoding(
            name="qwen",
            pat_str=(
                r"""(?i:'s|'t|'re|'ve|'m|'ll|'d)|[^\r\n\p{L}\p{N}]?\p{L}+"""
                r"""|\p{N}{1,3}| ?[^\s\p{L}\p{N}]+[\r\n]*|\s*[\r\n]+|\s+(?!\S)|\s+"""
            ),
            mergeable_ranks=mergeable_ranks,
            special_tokens=self._SPECIAL_TOKENS,
        )

    def count(self, text: str) -> int:
        if not text:
            return 0
        return len(self._encoding.encode(text, allowed_special="all"))


def counter_from_env() -> tuple[TokenCounter, str]:
    """按 ``LLM_TOKENIZER`` 选择计数器:

    - ``tiktoken`` → cl100k_base 通用近似口径;
    - ``qwen`` / ``qwen-tiktoken`` → Qwen 官方词表精确口径
      (词表文件缺失直接报错并给出初始化命令,不静默换口径);
    - 其余/未设置 → 保守口径。

    tiktoken 库未安装时两种精确口径都回落保守口径(环境缺失,版本号随回落
    写入工件,口径可辨)。返回 (counter, version)。
    """

    mode = (os.getenv("LLM_TOKENIZER") or "").strip().lower()
    if mode in {"tiktoken", "cl100k"}:
        try:
            return TiktokenCounter(), TIKTOKEN_TOKENIZER_VERSION
        except ImportError:  # 环境未装 tiktoken → 保守口径兜底
            pass
    elif mode in {"qwen", "qwen-tiktoken"}:
        try:
            return QwenTiktokenCounter(), QWEN_TIKTOKEN_VERSION
        except ImportError:  # 环境未装 tiktoken → 保守口径兜底
            pass
    return ConservativeTokenCounter(), CONSERVATIVE_TOKENIZER_VERSION


def _init_qwen_vocab(url: str | None = None) -> Path:
    """下载 Qwen 官方词表到本地缓存(一次性;之后计数零网络)。"""

    import urllib.request

    target_url = url or os.getenv("QWEN_TIKTOKEN_URL") or _DEFAULT_QWEN_VOCAB_URL
    destination = Path(os.getenv("QWEN_TIKTOKEN_FILE") or _DEFAULT_QWEN_VOCAB)
    destination.parent.mkdir(parents=True, exist_ok=True)
    print(f"下载 Qwen 词表:{target_url}")
    urllib.request.urlretrieve(target_url, destination)  # noqa: S310 - 官方词表源,可由参数覆盖
    lines = sum(1 for _ in destination.open("rb"))
    if lines < 100_000:
        destination.unlink(missing_ok=True)
        raise RuntimeError(f"词表行数异常({lines} 行,应为 151,643),已删除;请检查下载源")
    print(f"已缓存 {lines} 行 → {destination}")
    return destination


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Token 计数口径工具")
    parser.add_argument(
        "--init-qwen",
        nargs="?",
        const="",
        metavar="URL",
        help=f"下载 Qwen 官方词表到本地缓存(默认源 {_DEFAULT_QWEN_VOCAB_URL};传 URL 可覆盖)",
    )
    args = parser.parse_args()
    if args.init_qwen is not None:
        _init_qwen_vocab(args.init_qwen or None)
    else:
        parser.print_help()
