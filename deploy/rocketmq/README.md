# RocketMQ P4 运维说明

本目录部署一个 NameServer 和一个 Broker+Proxy（Local Mode）。它是单节点、单副本，**不具备高可用能力**；Broker 不可用时，业务事务仍只提交到 PostgreSQL，事件保留在 `runtime.outbox_event`，待 Broker 恢复后由 Data Plane JVM 内的 Relay 重投。

Compose 不映射任何 RocketMQ 端口到主机：NameServer、Broker 与 Proxy 仅供同一 Docker 网络内的 Data Plane 使用。镜像固定为 `apache/rocketmq:5.3.2`；`rmq-init` 显式创建四个 Topic 和 `bdlh-notification-consumer` 消费组。

## 正常启用

1. 设置 `BDLH_RUNTIME_DATA_MODE=java`、随机 `JAVA_DATA_INTERNAL_TOKEN`，并将 `ROCKETMQ_ENABLED=true`。
2. 启动 Compose。`rmq-init` 成功结束后，Data Plane 才会启动。
3. 通过服务凭证调用 `GET /internal/v1/ops/outbox` 观察 `pending`、`publishing`、`failed` 和最老待投递事件年龄。

## Retry、DLQ 与补偿

Consumer 返回失败时由 RocketMQ 进行重试，超过 Broker 的组重试策略后进入该消费组的 DLQ。查看消费进度和 DLQ 时，临时进入 Broker 容器执行 `sh mqadmin consumerProgress -n rmq-namesrv:9876 -g bdlh-notification-consumer`；不要常驻 Dashboard。

Outbox 发布失败达到 8 次会标记为 `FAILED` 且 `compensation_required=true`。完成事件内容、Broker 恢复与下游影响确认后，使用服务凭证调用 `POST /internal/v1/ops/outbox/{event_id}/requeue` 进行人工重投；此操作仅接受 `FAILED` 事件，并清除旧 claim。由于消费者使用 `(consumer_group, event_id)` Inbox 去重，重投不会重复写入通知投影。
