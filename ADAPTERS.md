# DSH-ELM 适配器与迁移 CLI

这些文件只操作调用者指定的快照和目标 SQLite 路径，不连接生产实例。目标实例未开放远程只读入口，因此 QQ Bridge 适配器默认把只有 `status=ok, retcode=0` 的 OneBot 响应判为 `unknown`。

## 运行

从 `outputs` 目录执行：

```powershell
python migrate.py --source .\snapshot\social-v2.json --target .\isolated\elm.sqlite --dry-run
python migrate.py --source .\snapshot\social-v2.json --target .\isolated\elm.sqlite --apply
python migrate.py --target .\isolated\elm.sqlite --verify
python migrate.py --target .\isolated\elm.sqlite --rollback --backup .\isolated\elm.sqlite.bak.20261103-120000
```

支持 `social-v2.json`、候选 `MEMORIES/*.jsonl` 和只读 `history.sqlite` 快照。`--apply` 会在已有目标文件旁创建时间戳备份；`--dry-run` 不插入事件；重复 `--apply` 使用 `event_id/idempotency_key` 幂等。

## 回执适配

```python
from adapters import adapt_receipt

adapt_receipt({"status": "ok", "retcode": 0})
# ReceiptStatus(state="unknown", ...)

adapt_receipt({"ok": True, "message_id": "m-1"})
# ReceiptStatus(state="confirmed", ok=True, ...)
```

只有显式 `ok is True`，或经过上游明确标记的 `confirmed is True` 并且带 receipt/message 标识，才会进入 `real_conversation` 事件。未知/失败回执不会阻塞正常 QQ 回复，也不会生成 ELM evidence。

## 限制

- 迁移只生成 `learning_events`；`experiences`、`experience_evidence`、版本和学习任务必须由 ELM 核心与验证器生成。
- social-v2 的 `tail`/短文本只作来源引用，不能当完整聊天原文。
- `activeTopics`、`pendingThoughts`、模型输出和摘要标为派生来源，不能作为独立真实证据。
- 生产迁移、配置写入、QQ 发送和插件安装必须在单独审批后执行。
