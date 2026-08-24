"""天气域插件入口。"""

from __future__ import annotations

from typing import Any

from bdlh_runtime.domains.plugin import DomainPlugin
from bdlh_runtime.domains.weather.manifests import build_weather_descriptor
from bdlh_runtime.domains.weather.runtime import WeatherRuntime
from bdlh_runtime.domains.weather.selector import WeatherCognitiveSelector


def install_weather(ctx: Any) -> DomainPlugin:
    descriptor = build_weather_descriptor(ctx.snapshot)
    return DomainPlugin(
        domain="weather",
        runtime=WeatherRuntime(),
        descriptor=descriptor,
        selector=WeatherCognitiveSelector(),
    )
