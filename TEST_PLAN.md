# DSH-ELM 离线测试计划

这些测试只针对隔离数据库、临时目录和模拟 Bridge，不连接 QQ/DSH 实例，不读取生产 `state/`。

## 必测行为

| 编号 | 场景 | 断言 |
|---|---|---|
| T01 | 初始化 SQLite | 五张 ELM 表存在；WAL、busy timeout、外键启用；schema version 可读 |
| T02 | 用户/群聊隔离 | scope=A 的事件/经验在 scope=B 检索不到；owner 与 conversation scope 不能越权 |
| T03 | 事件幂等 | 相同 event/idempotency key 重放不新增记录、不覆盖原始事件 |
| T04 | evidence 唯一 | 同一 `(experience_id,event_id)` 重复写入被拒绝或幂等返回 |
| T05 | 生命周期 | candidate → testing → established 需要验证；conflicted/retired 不绕过硬过滤 |
| T06 | 回执 unknown | 仅生成、入队、超时、`ok=false` 或缺少可信关联 ID 时不产生成功发送证据 |
| T07 | 回执 confirmed | 模拟适配器明确返回 confirmed 时才记录 `assistant_message_sent` |
| T08 | 检索上限 | 候选最多 10 条，最终注入最多 3 条；scope/禁用/冲突先硬过滤 |
| T09 | tokenizer 预算 | 注入正文超过预算时截断或放弃；实际测量值不超过配置上限 |
| T10 | 关闭旁路 | `enabled=false` 或任一灰度开关关闭时，原调用路径继续，ELM 不阻塞/不写入 |
| T11 | 异步失败 | SQLite 写失败后不抛出到 QQ 回复路径；仅记录结构化失败并进入有界补偿状态 |
| T12 | 迁移 dry-run | dry-run 不创建/修改目标生产数据库；输出预期行数与过滤/去重对账 |
| T13 | 迁移幂等 | 隔离副本连续 `--apply` 两次，第二次新增记录为 0 |
| T14 | 迁移 verify | 主键、外键、NULL、编码、长文本、scope 和抽样一致性校验通过 |
| T15 | rollback | 仅对验证过的隔离备份回滚；失败事务不留下半完成状态 |
| T16 | 自噬阻断 | `synthetic`/`elm_generated`/模型自评/注入文本不能作为独立真实 evidence |
| T17 | 提示注入 | 经验文本只能作为背景参考，不能改变安全规则、工具权限或人格核心 |
| T18 | 配额/熔断 | 学习调用、token、队列、重试均有上限；耗尽后延迟或旁路，不影响聊天 |

## 推荐运行方式

在 `outputs/dsh-elm` 目录、临时虚拟环境和临时数据库中运行：

```powershell
python -m pytest -q
python migrate.py --source <fixture> --target <temp-db> --dry-run
python migrate.py --source <fixture> --target <temp-db> --apply
python migrate.py --target <temp-db> --verify
python migrate.py --source <fixture> --target <temp-db> --apply
python migrate.py --target <temp-db> --verify
python migrate.py --target <temp-db> --rollback --backup <verified-backup>
```

若运行环境没有 pytest，测试套件应提供标准库 `unittest` 入口。任何依赖目标实例、真实 QQ 回执、生产数据库或未授权消息正文的测试都必须标记为 `not run`，不能标记为通过。
