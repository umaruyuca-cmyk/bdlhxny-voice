"""演示注入端点（设计文档 §4.8、§6.1、C-4、WO-T1-7）。

``POST /internal/demo/events``：写入 ``source=demo_inject`` 的 ``WatchEvent``，
走与真实事件完全相同的后续链路（唤醒 → 解读 → 通知）。该路由**仅在演示部署档**
（``BDLH_DEMO_MODE=true``）注册；非 demo 档下路由不存在（404），不依赖「隐藏」。

C-4：注入事件在负载 / 通知 / 证据链 / UI 四处携带「演示注入」标记——本端点负责
负载层（``source=demo_inject``）与 ``payload.demo=True``，通知层透传由 WO-T1-6
``WatchNotification.source`` 承载。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from bdlh_runtime.watch.events import WatchEvent

from ..context import ApiContext

# 演示事件用保留 rule_id（watch_event.rule_id 无外键约束；0 表示演示合成事件）
_DEMO_RULE_ID = 0


class DemoEventRequest(BaseModel):
    """演示注入请求体。

    - ``type``：事件类型（price_threshold / daily_briefing / post_market_review）；
    - 价格阈值：``symbol`` + ``pct``（涨跌幅百分点，负为下跌）或 ``abs_price``；
      ``direction`` 可选，缺省由 pct 符号推断。
    - 定时类：仅 ``type`` 即可（负载只含触发事实）。
    """

    type: str = Field(..., description="事件类型")
    symbol: str | None = None
    pct: float | None = None
    abs_price: float | None = None
    direction: str | None = None
    # 定时类可选的交易日覆盖（缺省取当日北京时间日期）
    trading_day: str | None = None


def register(router: APIRouter, ctx: ApiContext) -> None:
    @router.post("/internal/demo/events")
    async def inject_demo_event(request: DemoEventRequest) -> dict[str, Any]:
        event_store = getattr(ctx.application, "watch_event_store", None)
        if event_store is None:
            raise HTTPException(status_code=503, detail="watch_event_store 未装配")

        event_type = request.type
        now = datetime.now(UTC)
        # 演示事件 dedupe_key 含 uuid，允许同标的同日多次注入（演示迭代需要）
        dedupe_key = f"demo:{event_type}:{uuid4()}"
        payload: dict[str, Any] = {"demo": True}

        if event_type == "price_threshold":
            symbol = request.symbol
            if not symbol:
                raise HTTPException(status_code=400, detail="price_threshold 需要 symbol")
            if request.pct is not None:
                pct = float(request.pct)
                direction = request.direction or ("down" if pct < 0 else "up")
                # 合成参考价便于解读与展示；演示数据非真实市场事实（C-4）
                prev_close = 100.0
                price = round(prev_close * (1 + pct / 100.0), 4)
            elif request.abs_price is not None:
                price = float(request.abs_price)
                direction = request.direction or "down"
                prev_close = None
                pct = None
            else:
                raise HTTPException(
                    status_code=400, detail="price_threshold 需要 pct 或 abs_price"
                )
            payload.update(
                {
                    "symbol": symbol,
                    "direction": direction,
                    "price": price,
                    "prev_close": prev_close,
                    "pct_change": pct,
                    "currency": "CNY",
                    "source_time": now.isoformat(),
                    "quality": "OK",
                }
            )
        elif event_type in {"daily_briefing", "post_market_review"}:
            beijing_day = (now.astimezone(timezone(timedelta(hours=8)))).date().isoformat()
            payload.update({"trading_day": request.trading_day or beijing_day})
        else:
            raise HTTPException(
                status_code=400,
                detail=f"不支持的事件类型：{event_type!r}",
            )

        event = WatchEvent(
            rule_id=_DEMO_RULE_ID,
            type=event_type,
            source="demo_inject",
            payload=payload,
            dedupe_key=dedupe_key,
            occurred_at=now,
        )
        try:
            persisted = event_store.append(event)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=f"事件写入失败：{type(exc).__name__}") from exc
        return {"event_id": str(persisted.id), "dedupe_key": persisted.dedupe_key, "source": persisted.source}
