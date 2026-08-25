"""Token 计数口径测试:保守口径不变性 + tiktoken 可选精确口径三分支。"""

from __future__ import annotations

from pathlib import Path

import pytest

from bdlh_runtime.context import (
    CONSERVATIVE_TOKENIZER_VERSION,
    TIKTOKEN_TOKENIZER_VERSION,
    ConservativeTokenCounter,
    TiktokenCounter,
    counter_from_env,
)

_TEXT = "会议决定使用PostgreSQL数据库,禁止修改文件。"
_MIXED = "上下文压缩 context compression 12345"


def test_conservative_counter_counts_cjk_as_one_token_each() -> None:
    counter = ConservativeTokenCounter()
    assert counter.count("") == 0
    # 15 个 CJK 字符 + 2 个标点(,。)各 1 token + "PostgreSQL"(10 拉丁 → ceil(10/4)=3)
    assert counter.count(_TEXT) == 17 + 3


def test_tiktoken_counter_counts_exact_encoding() -> None:
    counter = TiktokenCounter()
    assert counter.count("") == 0
    exact = counter.count(_TEXT)
    assert exact > 0
    # cl100k_base 下中文通常每字 0.6~1 token:一般低于保守口径(近似上界)
    assert exact <= ConservativeTokenCounter().count(_TEXT)
    assert counter.count(_TEXT) == counter.count(_TEXT)  # 确定


def test_both_counters_are_deterministic_on_same_text() -> None:
    conservative = ConservativeTokenCounter().count(_MIXED)
    tiktoken = TiktokenCounter().count(_MIXED)
    assert conservative > 0 and tiktoken > 0
    # 两口径对同一文本的计数各自确定
    assert conservative == ConservativeTokenCounter().count(_MIXED)
    assert tiktoken == TiktokenCounter().count(_MIXED)


def test_counter_from_env_default_is_conservative(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LLM_TOKENIZER", raising=False)
    counter, version = counter_from_env()
    assert isinstance(counter, ConservativeTokenCounter)
    assert version == CONSERVATIVE_TOKENIZER_VERSION


def test_counter_from_env_tiktoken_switch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_TOKENIZER", "tiktoken")
    counter, version = counter_from_env()
    assert isinstance(counter, TiktokenCounter)
    assert version == TIKTOKEN_TOKENIZER_VERSION


def test_counter_from_env_tiktoken_missing_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_TOKENIZER", "tiktoken")
    real_import = __builtins__["__import__"] if isinstance(__builtins__, dict) else __builtins__.__import__

    def _no_tiktoken(name, *args, **kwargs):
        if name == "tiktoken":
            raise ImportError("No module named 'tiktoken'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", _no_tiktoken)
    counter, version = counter_from_env()
    assert isinstance(counter, ConservativeTokenCounter)
    assert version == CONSERVATIVE_TOKENIZER_VERSION


def test_tiktoken_counter_docstring_marks_approximation() -> None:
    # 口径近似性必须在代码注释中标明:cl100k_base 为近似口径,跨口径不可比
    assert "近似" in (TiktokenCounter.__doc__ or "")


# ── Qwen 官方词表口径 ─────────────────────────────────────────────────────

_QWEN_VOCAB = Path(__file__).resolve().parents[2] / "var" / "cache" / "qwen.tiktoken"
_has_qwen_vocab = _QWEN_VOCAB.is_file()


def test_qwen_counter_missing_vocab_raises_clear_error(tmp_path: Path) -> None:
    from bdlh_runtime.context import QwenTiktokenCounter

    with pytest.raises(FileNotFoundError, match="init-qwen"):
        QwenTiktokenCounter(vocab_path=tmp_path / "nope.tiktoken")


@pytest.mark.skipif(not _has_qwen_vocab, reason="本地未缓存 qwen.tiktoken(先 --init-qwen)")
def test_qwen_counter_counts_chinese_more_efficiently_than_conservative() -> None:
    from bdlh_runtime.context import QwenTiktokenCounter

    counter = QwenTiktokenCounter()
    assert counter.count("") == 0
    qwen = counter.count(_TEXT)
    assert qwen > 0
    # Qwen 中文 BPE 合并词元:显著低于保守口径,也低于 cl100k 近似
    assert qwen < ConservativeTokenCounter().count(_TEXT)
    assert qwen < TiktokenCounter().count(_TEXT)
    assert counter.count(_TEXT) == qwen  # 确定


@pytest.mark.skipif(not _has_qwen_vocab, reason="本地未缓存 qwen.tiktoken(先 --init-qwen)")
def test_qwen_counter_counts_special_tokens_as_single_tokens() -> None:
    from bdlh_runtime.context import QwenTiktokenCounter

    counter = QwenTiktokenCounter()
    # 两个特殊词元各 1 个 + 文本若干;不得因特殊词元抛错
    special = counter.count("<|im_start|>你好<|im_end|>")
    plain = counter.count("你好")
    assert special == plain + 2


@pytest.mark.skipif(not _has_qwen_vocab, reason="本地未缓存 qwen.tiktoken(先 --init-qwen)")
def test_counter_from_env_qwen_branch(monkeypatch: pytest.MonkeyPatch) -> None:
    from bdlh_runtime.context import QWEN_TIKTOKEN_VERSION, QwenTiktokenCounter

    monkeypatch.setenv("LLM_TOKENIZER", "qwen")
    counter, version = counter_from_env()
    assert isinstance(counter, QwenTiktokenCounter)
    assert version == QWEN_TIKTOKEN_VERSION
    monkeypatch.setenv("LLM_TOKENIZER", "qwen-tiktoken")
    assert counter_from_env()[1] == QWEN_TIKTOKEN_VERSION


def test_counter_from_env_qwen_missing_vocab_fails_not_silent(monkeypatch: pytest.MonkeyPatch) -> None:
    # 词表缺失必须显式失败,不得静默换口径(env 真源纪律)
    monkeypatch.setenv("LLM_TOKENIZER", "qwen")
    monkeypatch.setenv("QWEN_TIKTOKEN_FILE", str(Path(__file__).parent / "definitely-missing.tiktoken"))
    with pytest.raises(FileNotFoundError, match="init-qwen"):
        counter_from_env()
