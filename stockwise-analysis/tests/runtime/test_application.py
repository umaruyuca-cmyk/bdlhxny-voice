import pytest

from stockwise_analysis.config import Settings
from stockwise_analysis.runtime.application import create_application
from stockwise_analysis.runtime.errors import ConfigurationError


def test_production_requires_persistent_checkpointer():
    """生产配置不能静默退化到内存 Checkpointer。"""

    with pytest.raises(ConfigurationError):
        create_application(Settings(environment="production"))
