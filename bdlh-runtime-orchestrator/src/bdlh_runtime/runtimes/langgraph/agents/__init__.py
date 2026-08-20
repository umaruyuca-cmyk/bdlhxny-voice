"""模型/Agent 边界。

Graph 节点只依赖这些接口，不直接绑定某个模型供应商或提示词实现。
"""

from .direct_response_model import (
    DeterministicDirectResponseModel,
    DirectResponseModel,
    create_direct_response_model,
)

__all__ = [
    "DeterministicDirectResponseModel",
    "DirectResponseModel",
    "create_direct_response_model",
]
