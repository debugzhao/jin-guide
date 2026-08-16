# Prompt Registry

## 目标

项目采用 Git-first Prompt Registry：Prompt 定义与代码一起评审、发布和回滚，不依赖运行时数据库或外部托管平台。业务调用只能通过 `app.prompts.prompt_registry` 获取当前版本。

## 目录与版本

- `app/prompts/active_versions.yaml`：每个 Prompt 当前启用版本。
- `app/prompts/definitions/<prompt_name>/vN.yaml`：不可变版本定义。
- `app/prompts/registry.py`：加载、路径一致性和启动校验。
- `app/prompts/models.py`：严格变量渲染、模型参数和调用元数据。
- `app/prompts/version_hashes.yaml`：已登记版本内容哈希，防止旧版本被静默覆盖。

已经上线的版本不得原地修改。变更时新建 `v2.yaml`，完成测试后再修改启用版本；回滚只需恢复版本清单。

## 安全边界

Registry 只管理固定指令、模板和模型参数。报告、摘要、检索结果及用户输入仍按低权限数据传入；工具权限、参数验证、引用白名单和输出合规由代码控制，不能依赖 Prompt。

模板使用 Python `string.Template` 的 `$variable` 语法，不支持表达式或函数。缺变量、多余变量、未声明变量均直接失败。

## 可观测性

每次调用发送 `prompt_name`、`prompt_version`、`prompt_hash` 和 `invocation_id` 给 LiteLLM/LangSmith，并 best-effort 写入 `prompt_invocations`。审计表不保存 Prompt 正文、用户原文和动态上下文，只保存白名单关联 ID、调用状态、耗时和错误类型。
