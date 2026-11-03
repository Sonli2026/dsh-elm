# DSH-ELM 独立核心模块

这是阶段 1 的隔离实现：默认只写指定的本地 SQLite 路径，不连接 DSH/QQ，也不会修改生产配置。目标实例接入由适配器另行完成。它是可运行的独立模块，不代表已部署到目标实例。

要求 Python 3.10+，仅使用标准库：

```powershell
python -m unittest discover -s tests -v
python -m elm.cli init --db .\data\elm.sqlite
python -m elm.cli stats --db .\data\elm.sqlite
```

若环境没有 `python` 在 PATH 中，可使用 DSH runtime 自带的 Python 3.12 解释器运行同样命令。

核心行为：

- 独立 SQLite，启用外键、WAL、busy timeout、FULL synchronous 和 schema version。
- 五张逻辑表：`learning_events`、`experiences`、`experience_evidence`、`experience_versions`、`learning_runs`。
- 事件和学习任务使用幂等键；证据使用 `UNIQUE(experience_id,event_id)`。
- scope/owner 硬隔离；检索最多 10 条，注入最多 3 条，默认新增注入预算 500 个估算 token。
- 经验状态：`candidate`、`testing`、`established`、`conflicted`、`retired`。
- 注入文本只是背景参考，调用方必须继续使用原 DSH 人格和 QQ 工具权限。

当前 tokenizer 使用可替换的估算函数（中英文约按 4 字符/token）；接入目标模型前必须替换为实际 tokenizer 并重新验证 500 token 门槛。

## 隔离迁移与回执适配

在本目录执行（需要 Python 3.10+）：

```powershell
python migrate.py --source .\snapshot\social-v2.json --target .\data\elm.sqlite --dry-run
python migrate.py --source .\snapshot\social-v2.json --target .\data\elm.sqlite --apply
python migrate.py --target .\data\elm.sqlite --verify
python migrate.py --target .\data\elm.sqlite --rollback --backup .\data\elm.sqlite.bak.<timestamp>
```

`sources.py` 只读解析 QQ `social-v2.json`、候选 `MEMORIES/*.jsonl` 和旧 `history.sqlite` 快照；`adapters.py` 将明确 `ok === true` 或上游确认的 `confirmed` 回执转换为 ELM 成功状态。只有 `status=ok`/`retcode=0` 的 OneBot 外层响应会被标记为 `unknown`，不会进入真实发送证据。

迁移默认只写指定目标路径，不连接 DSH/QQ，也不修改生产配置。目标实例接入需要另写桥接层并经过回执、scope、故障旁路和人工验收。

## fail-open 运行时入口

`elm.runtime.ELMRuntime` 为 DSH/QQ 适配器提供旁路入口。关闭、数据库异常或适配器异常时返回空结果/`None`，不把错误抛进正常 QQ 回复路径：

```python
from elm import ELMConfig, ELMRuntime

runtime = ELMRuntime("./data/elm.sqlite", ELMConfig(enabled=False))
runtime.observe_event({"scope": "private:demo", "event_type": "message_received",
                       "idempotency_key": "demo-1", "provenance": "real_conversation"})
context = runtime.retrieve_context(scope="private:demo", query="demo")
runtime.close()
```

当前离线测试为 12 项通过；测试使用临时目录和 SQLite，不读取生产状态。实际实例回执、目标 tokenizer 和 hier-memory API 仍需现场核验。
