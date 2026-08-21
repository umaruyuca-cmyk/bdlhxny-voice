"""可替换的文本编码器。

生产快路径使用 ``QwenEmbeddingEncoder``（OpenAI 兼容 /v1/embeddings，Qwen3 向量模型）。
词法哈希编码器仅存在于测试 helpers，不得进入产品装配。
"""

from __future__ import annotations

from collections import OrderedDict
from typing import Protocol, runtime_checkable


class EncoderUnavailableError(RuntimeError):
    """向量化服务不可用；快路径应视为未命中，放行完整管线。"""


@runtime_checkable
class Encoder(Protocol):
    """把文本编成定长向量；同一实现必须对相同输入给出相同向量。"""

    def encode(self, texts: list[str]) -> list[list[float]]: ...


class QwenEmbeddingEncoder:
    """Qwen3 向量模型编码器（OpenAI 兼容 /v1/embeddings）。

    生产快路径唯一编码器；查询侧带进程内 LRU 缓存，重复句子不再请求。
    服务调用失败抛 ``EncoderUnavailableError``：启动期预编码失败会让装配
    直接报错（配置错误必须显性暴露）；运行期由 SemanticRouter 降级为未命中。
    同步阻塞实现，调用方应放入线程（见 SemanticRouteSelector）。
    """

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        api_key: str | None = None,
        timeout_seconds: float = 10.0,
        cache_size: int = 512,
    ) -> None:
        if not base_url:
            raise ValueError("base_url is required")
        if not model:
            raise ValueError("model is required")
        self._endpoint = base_url.rstrip("/") + "/embeddings"
        self._model = model
        self._api_key = api_key
        self._timeout_seconds = timeout_seconds
        self._cache: OrderedDict[str, list[float]] = OrderedDict()
        self._cache_size = cache_size

    def encode(self, texts: list[str]) -> list[list[float]]:
        results: list[list[float] | None] = []
        missing_texts: list[str] = []
        missing_indexes: list[int] = []
        for index, text in enumerate(texts):
            cached = self._cache.get(text)
            if cached is not None:
                self._cache.move_to_end(text)
                results.append(cached)
            else:
                results.append(None)
                missing_texts.append(text)
                missing_indexes.append(index)
        if missing_texts:
            vectors = self._encode_remote(missing_texts)
            for index, text, vector in zip(missing_indexes, missing_texts, vectors, strict=True):
                results[index] = vector
                self._cache[text] = vector
                self._cache.move_to_end(text)
                if len(self._cache) > self._cache_size:
                    self._cache.popitem(last=False)
        return [vector if vector is not None else [] for vector in results]

    def _encode_remote(self, texts: list[str]) -> list[list[float]]:
        import httpx

        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        try:
            # trust_env=False：向量服务是内网/容器网调用，禁止被系统代理
            # （Windows 注册表代理等）截走——否则 localhost 请求会被代理打成 502。
            with httpx.Client(timeout=self._timeout_seconds, trust_env=False) as client:
                response = client.post(
                    self._endpoint,
                    headers=headers,
                    json={"model": self._model, "input": texts},
                )
                response.raise_for_status()
                payload = response.json()
        except Exception as exc:  # noqa: BLE001
            raise EncoderUnavailableError(
                f"Qwen 向量服务不可用（{self._endpoint}）：{type(exc).__name__}"
            ) from exc
        try:
            data = sorted(payload["data"], key=lambda item: item["index"])
            return [list(map(float, item["embedding"])) for item in data]
        except Exception as exc:  # noqa: BLE001
            raise EncoderUnavailableError("Qwen 向量服务返回结构异常") from exc
