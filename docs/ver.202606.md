# GoalKeepr 代码审查计划

**会话 ID**: 019e88c7-5787-7c12-8516-5014cdc7abd4
**日期**: 2026（基于上下文）
**审查目标**: GoalKeepr Telegram 机器人完整代码库审查（无未提交变更；工作树干净，位于 master 分支并与 origin 同步；审查当前全部源代码状态）。

## 背景说明
用户请求“审查代码”。根据初始 git status，工作树干净，位于 master 并与 origin/master 同步，没有指定特定 PR、分支差异或变更文件。因此，本次是对整个活跃 Python 代码库的全面审查，而非增量 diff 审查。

审查技能（`/home/scys/.grok/bundled/skills/review/SKILL.md`）主要用于基于 diff 的审查（本地变更、分支或 GitHub PR），并使用专用的 reviewer persona。它会生成结构化的 Markdown 审查发现，以及（本地/分支模式下的）摘要文件。对于没有 diff 的完整项目审查，我们将适配该流程：
- 使用 reviewer persona 指令（从 `.../shared/personas/reviewer.md` 读取）。
- 利用已完成的只读探索（通过 `read_file`、`grep`、`list_dir`、`run_terminal_command`（仅 ls）、以及 `spawn_subagent` + `subagent_type=explore` 完成）。
- 启动一个或多个 general-purpose 子代理，在 prompt 中注入 reviewer persona 指令，任务是审查特定模块/文件（根据需要使用 read_file/grep），并严格按照技能要求的格式输出结构化发现（## Summary + ## Issues，包含 severity/file:line/Description/Suggestion/Status）。
- 汇总生成规范的审查产物（例如参考 `/tmp/grok-review-*.md` + summary）。
- **绝不修改任何源代码**；仅生成审查报告（放在 /tmp 或项目内 review/ 目录）。
- 交叉参考 CLAUDE.md 架构说明、README 流程图、pyproject.toml、tests 以及 example/main.ini。

这与“当用户要求 'review'、'code review' 时使用”的指导一致，同时遵守 plan mode 限制（规划阶段仅可编辑 plan.md；批准并 exit_plan_mode 前所有其他操作均为只读）。

**为什么现在进行审查？** 项目已演进（新增 stats.py、captcha_stats、system_*、chat/ 子包；member_captcha 重构引入双 Session 类；worker 逻辑合并到 main.py）。此前更广泛的测试已被精简（仅剩陈旧 .pyc）。一次全新审查可揭示技术债务、正确性风险（尤其是核心 captcha 功能），以及维护问题。

## 推荐实施方法
1. **准备阶段（规划中已完成）**：使用工具对所有层次进行彻底探索。子代理探索已产出详细的模块摘要 + 标记的风险（见下文“探索发现的关键领域与已知风险”）。已读取 reviewer persona + review skill 的输出契约。

2. **执行阶段（批准后）**：
   - 重新读取 reviewer persona 指令（存储为 `reviewer_persona_instructions`）。
   - 将审查“目标”定义为逻辑模块（无单一 diff；可将整个树或按子系统视为目标，使用 `git show HEAD -- <path>` 或直接全文件读取）。
   - 针对每个主要领域，spawn 一个以 `[reviewer]` 为前缀的 general-purpose 子代理：
     - Prompt = persona + “你正在审查模块 X 的当前完整代码（未提供 diff；审查绝对正确性而非仅变更）。读取列出的文件。根据需要使用 `read_file` + `grep` 获取上下文。将结构化发现写入 <特定审查文件路径>，严格遵循此格式：[粘贴技能中的 ## Summary / ## Issues 模板]。在正确性、边界情况、竞态、错误处理上力求细致。每个问题必须引用 file:line。Severity: bug | suggestion | nit。Status: open。”
     - description="[reviewer] full review: <领域>"
     - capability 设为只读。
   - 覆盖领域（可并行或顺序，以避免上下文膨胀）：
     - 核心运行时：main.py + manager/manager.py + database.py + worker 残留。
     - Captcha 核心（最高风险/影响）：handlers/member_captcha/* 全部 + main/manager 中的交叉调用。
     - 支撑层：utils/（advertising + asr/tts/comfy）、handlers/utils/*（llm/txt/base）。
     - 命令与处理器：活跃命令（k、sb、whoami、group_setting、captcha_stats、system_*、default）+ 已注释/可选功能（image 重量级 worker、chat/ 等）+ handlers/__init__。
     - Manager 辅助：manager/group.py + settings.py。
     - 测试：覆盖率、缺口、生产保真度（FakeRedis、mock）。
   - 子代理完成后：读取其输出的 review 文件，按严重程度统计问题（解析标题），生成主摘要（参考技能 Step 3 本地/分支模式），并生成合并审查文档。
   - 可选：额外生成简短“Top Issues”执行摘要供用户。
   - 清理：不修改源代码；保留审查产物（或使用 python uuid 生成 REVIEW_ID 后复制到 ./review/ 或 /tmp）。

3. **审查标准**（直接来自 persona + 项目上下文）：
   - 正确性优先，风格其次。
   - 边界情况、错误处理缺口、竞态条件、异步安全。
   - 每个发现必须有具体行号引用。
   - **绝不自己提出或进行代码修复**。
   - 项目特有重点：Redis/SQLite 回退一致性、时区正确性（大量 naive/aware 混用）、新旧双 session 状态、权限/限制泄漏风险、无 Redis 降级、worker 轮询可靠性、后台任务生命周期、密钥/配置处理、LLM/advertising 注入与 ReDoS 安全、关键路径的测试覆盖（尤其是调度 + events）。
   - Severity: bug（正确性、数据丢失、安全、卡死状态、时序错误）、suggestion（改进、技术债务、韧性）、nit（风格、注释、命名）。

4. **交付物**：
   - 结构化 review 文件（严格遵循 review skill 格式：## Summary（2-4 句总体评估）、## Issues，每条包含 File: path:LINE、Description、Suggestion、Status: open）。
   - Summary 文件（问题计数、Top issues、完整 review 路径）。
   - 最终响应：类似模式的报告（“完整代码库审查”）、覆盖的文件/领域、问题计数、Top issues 摘录、产物链接。
   - 不进行 GitHub PR 提交（不适用）。

5. **风险与权衡考虑**：
   - 完整审查 vs diff：选择完整审查，因为工作树干净 + 用户查询宽泛（“审查代码”）。按子系统拆分可保持子代理 prompt 可控。
   - 使用 spawn_subagent + persona 注入 vs 直接分析：遵循既定的 review skill 契约和 persona，保证输出一致且高质量。
   - 审查期间绝不修改源代码（强制）。
   - 陈旧 .pyc / 已删除测试源已记录，但非本次重点。
   - 若环境中无 Redis，部分路径会降级；审查会明确指出。

## 需审查的关键文件 / 模块（含可复用说明）
- **核心 / 入口**：
  - main.py（worker_loop、lazy_messages/sessions、startup_cleanup、events 导入；复用 manager、database）
  - manager/manager.py（Manager 单例、@register / register_event、Redis 优先+出错无回退的 lazy 调度、delete/send/reply 包装、get_redis、_format_sqlite_datetime、is_admin、get_user_extra_info；复用 database、settings）
  - database.py（单连接 + 锁的 aiosqlite；供 lazy + 启动使用）
  - manager/__init__.py（单例实例）
- **Captcha（核心功能，重点审查）**：
  - handlers/member_captcha/member_captcha.py（chat_member 入口、流程分发、安全兜底、统计）
  - handlers/member_captcha/session.py（新 CaptchaSession 主实现 + 旧版 legacy Session 兼容类 + “逐步迁移”注释；Redis HASH + 去重 SETNX；复用 manager）
  - handlers/member_captcha/validators.py（基础检查、通过 manager.group 获取验证方式、silence/sleep 处理、使用 legacy Session 的 create_verification_session）
  - handlers/member_captcha/security.py（restrict/restore、get_member_info + t.me 抓取、perform_security_checks（先 LLM 后 adv）、标记；复用 utils.advertising + handlers/utils/llm）
  - handlers/member_captcha/callbacks.py（验证、通过 helpers 解 MD5、管理员/自验证分流、adv/llm 标记分支、重试、重新生成+重调度）
  - handlers/member_captcha/events.py（注册的 lazy 事件：new_member_check、unban_member、safety_timeout_check + _kick_member reason 逻辑）
  - handlers/member_captcha/helpers.py（build_captcha_message + MD5 短回调 + ICONS、store/get/delete_callback_map、accepted_member + 耗时 + 头像探测）
  - handlers/member_captcha/config.py（常量：DELETED_AFTER=30、阈值、VerificationMode、CallbackOperation）
  - handlers/member_captcha/stats.py（静默 1s 超时的 _safe_* 递增、persons 集合）
  - handlers/member_captcha/exceptions.py（LogContext、*Error 子类）
  - 交叉：handlers/__init__.py（导出 captcha）、main.py（导入 events）、manager（lazy + events 字典）
- **Manager / 设置**：
  - manager/group.py（per-group new_member_check_method 的 settings_get/set；复用 redis）
  - manager/settings.py（SETTINGS_TEMPLATE 默认值）
- **处理器 / 命令（活跃 + 可选）**：
  - handlers/default.py、handlers/error.py
  - handlers/commands/__init__.py（选择性导入；大量已注释）
  - handlers/commands/k.py、sb.py、whoami.py（简单管理命令；使用 is_admin + lazy delete）
  - handlers/commands/group_setting.py + captcha_stats.py + system_*.py（活跃，部分需 Redis）
  - handlers/commands/chat/*（func_*.py；通过 Redis 实现 AI 上下文/配额；权限）
  - handlers/commands/image.py（重量级：Comfy worker 由 main 始终启动、PermissionManager、Task 队列、imgproxy 加密、LLM 优化；复用 utils.comfy_*）
  - 其他（已注释但代码存在）：sdxl.py、shorturl.py、translate/tts/asr 等
- **Utils**：
  - utils/advertising.py（每次调用都重新 load words/patterns、check_advertising；re.compile，在 security 路径中使用）
  - handlers/utils/llm.py（多模型垃圾检测，7s/模型、JSON 解析、提示注入面）
  - handlers/utils/txt.py（chat_completions + tg_generate_text；健壮的 _api_request 重试；通过 __init__ 再导出）
  - handlers/utils/base.py（tokens、chinese（未使用）、strip prefix）
  - utils/（asr.py、tts.py、comfy_api.py + comfy_workflow.py（硬编码 workflow）、sd_api.py 遗留）
- **测试**：
  - tests/conftest.py（FakeRedis 完整类型强制 + 过期、mock_manager fixture、ad/llm patch）
  - tests/test_session.py、test_callbacks.py、test_security.py、test_advertising.py、test_stats.py（对重构后模块的强单元覆盖）
  - 注：许多历史更广测试仅剩陈旧 .pyc；当前无 worker、完整流程、events.py、legacy Session、无 Redis 端到端等的测试。
- **配置 / 文档**：
  - pyproject.toml（依赖、pytest asyncio auto）
  - example/main.ini + main.ini（各 section）
  - README.md（流程图与代码匹配）、CLAUDE.md（架构）
  - docker/（startup）、worker.py（占位桩）

**需大量复用的现有函数/工具**：
- Reviewer persona: /home/scys/.grok/bundled/skills/shared/personas/reviewer.md（原样前置）。
- Review 输出契约 + 步骤：来自 /home/scys/.grok/bundled/skills/review/SKILL.md（尤其是 Summary/Issues 格式、severity 规则、“不仅读 diff 还要读文件”、计数、不自修复）。
- 测试中的 FakeRedis + mock 模式（tests/conftest.py，若需活体验证时）。
- LogContext 用于发现中的结构化记录。
- 现有测试模式用于“该测试能否捕获 X？”的验证。

## 探索发现的关键领域与已知风险（审查时需明确验证/展开）
（来自子代理输出的浓缩；审查子代理必须重新检查源代码，不要仅信任本摘要。）

**高严重度（bug）候选**：
- main.py + manager.py：双重 `run_until_disconnected`（main.py:201-202 调用 start，而 start 内部已执行；存在不可达代码）。后台任务（worker_loop、txt2img_worker）被 create 但从未 cancel/gather；stop() 仅设置 flag。txt2img 即使 image 命令被注释也始终启动。
- Redis 调度（manager.py delete_message/lazy_session）：zadd 等出错时 → return False / 静默丢弃，**无 SQLite 回退**（而 worker 始终同时处理两者）。调度时刻的瞬时 Redis 错误会导致踢人/解封/删除任务丢失。get_redis() 懒初始化无重试/重置。
- worker lazy_sessions (main.py)：出错时移除不一致（Redis：外层出错即移除；SQLite：func 出错时 continue 不删除）。格式假设（恰好 4 部分）。
- **Captcha 双存储 (session.py)**：CaptchaSession（主要实现，加入后使用）+ 旧版 `class Session`（validators/security 中仍在 create/save，用于 3s 窗口内的 bio/banned 载体；"member_captcha:{chat}:{user}" STRING 键，7d；create/save 逻辑有 if-exists 更新但总是重新 set）。注释承认是过渡。重加入仅清除 Captcha 字段。大多数路径不清理 legacy。测试从未执行 legacy。
- **events.py 中 advertising 的 unban bug**：_kick_member adv → 30d ban + return True；new_member_check/safety_timeout_check 无条件执行 `if kicked: lazy unban+60s`。对比：callbacks 自验证 adv 路径明确 delete new_member lazy + 不调度 unban（正确意图是 30d）。结果是 timeout 路径下 adv 实际仅封 ~60s（垃圾账号可很快重加）。文档字符串称 adv 30d。无测试覆盖 events.py 或此路径。
- 处处时区混用（grep 显示 70+ 处）：调度中使用 naive `datetime.now()`（events.py:79/129 unban、security auto_deleted、main worker .timestamp()、group_setting、k.py、image 等），与 aware `now(timezone.utc)` + Telethon date + fromisoformat + sqlite 'localtime' + manager _format（仅在有 tzinfo 时 astimezone → 本地 naive 字符串）混用。风险：30s 验证码 / 60s unban / 180s safety 时长错误、cost 计算、过期检查（validators.py:37）、DST/容器时区偏移。Redis .timestamp() 安全；混用路径不安全。
- 限制泄漏 / 卡死状态：restrict 失败早返回（无 safety/captcha → 未验证用户加入）；restrict 后错误留下 safety（好），但 safety/lazy 失败则永久禁言；accepted_member restore 失败早返回（无欢迎，限制是否解除？）；cb_map 未命中 → “已过期”但限制 + 待处理 lazy 仍存在；无 Redis：record_answer 等 noop → handle_self_verification 中正确点击返回 False（用户被永久限制）；重加入等场景。
- 回调映射 / 重启：startup_cleanup 仅清理 cb_map:*（Redis）；活跃 session/lazy 可能误触发或“过期”。cb_map 仅 Redis（无 sqlite 路径）。
- 无 Redis 降级：CaptchaSession.check_and_record 降级为 always-proceed；但许多路径（cb_map、record/get/flag、settings、stats 可选）noop 或导致验证失败。group_setting 等要求 Redis。

**中严重度（suggestion / 韧性 / 债务）**：
- 错误处理：到处宽泛 `except Exception` + log（许多流程不 re-raise）；SecurityCheckError 被抛出但 member_captcha 外层未显式捕获。LLM/advertising 有韧性（多模型、静默 stats），但无熔断。
- Worker 竞态 / 轮询：概率低但 zscan_iter + zrem 非原子；sqlite fetch-then-per-row-delete 存在窗口；并发 handler 调度 vs poll。
- 资源 / 生命周期：后台任务无引用用于取消；http_session 关闭；DB 单连接但锁串行化；get_user_extra_info 中的 aiohttp（security 抓取 bio 用 t.me）部分路径未复用 session。
- LLM/advertising 安全：用户 bio/name + additional 直接注入 LLM prompt（仅 JSON dump，无额外清理）；系统提示中文 + “仅输出 JSON”。Advertising：每次 check 都 re.compile（无缓存），管理员配置的 pattern → 每次加入都有 ReDoS 风险；words 是朴素子串匹配。
- 配置/密钥：main.ini 明文（token、ai.proxy_token、imgproxy 各种 key/salt/用于 AES 的 enc key）；无 env、无掩码。部分 section 未使用（oxford?）。
- 死亡/未使用代码：contains_chinese（已导出，0 调用处）；worker.py 占位；sd_api 遗留；部分已注释代码仍被导入/执行（image worker 始终启动）；已删除测试的陈旧 pyc。
- 测试缺口（会遗漏以上许多问题）：CaptchaSession + callbacks 分支 + security 单元 + adv 覆盖良好（FakeRedis 设计优秀）；对以下为零：完整 member_captcha 流程、events.py + _kick + timeout/safety、legacy Session、worker_loop/lazy_*、sqlite 回退调度、无 Redis 完整验证、时区、加入路径错误恢复、manager 真实 lazy 实现上下文。无已注册 handler + 调度的集成测试。
- 其他：sleep/离开后的权限检查；unban 总是全量恢复（无“之前是否被限制”检查）；dedup event_uid 回退在快速加入时可能碰撞；5 个随机图标（UX 好但）；始终运行的 worker；image 重量级（Comfy 自定义节点，无 chat 那样的用户配额）。

**低严重度（nits）**：日志/注释中英混用（符合 CLAUDE 风格）、过时 docstring（db “new conn per call”）、魔法数字重复（多处 DELETED_AFTER）、宽泛导入等。

审查者必须重新读取源代码以获得新鲜视角 + 引用确切行号（使用计划时的当前代码）。

## 验证部分（审查执行后）
- 运行完整测试套件：`uv run pytest -q --tb=no`（或带 dev 依赖）。验证全部通过（审查不产生代码变更，但确保基线）。
- 可选调用 check-work 技能（或手动）进行任何后续，但主要交付是审查输出。
- 若环境有 Telegram/Redis/Comfy，可手动抽查关键路径（非必需；测试中使用 mock）。
- 确认审查产物已写入且可解析（问题计数正则、file:line 引用有效）。
- 对于 TZ 或调度类问题：后续可添加针对性单元测试（不属于本次审查任务）。
- 端到端：审查报告本身应自包含且对维护者可执行。

## 执行步骤（exit_plan_mode + 批准后的高层步骤）
1. 生成 REVIEW_ID（uuid hex[:8]）+ 设置 umask；定义 review_file、summary_file 等（即使无 diff 也适配 skill）。
2. 加载 persona。
3. 为列出的领域 spawn 4-6 个 reviewer 子代理（尽可能并行）。
4. 等待，通过 get_command_or_subagent_output 或 resume 收集输出。
5. 解析/汇总计数 + top issues（对产生的 review 文件使用 read_file）。
6. 写入主摘要 + 向用户呈现文件路径。
7. （可选）将合并审查写入持久位置，如 `review/full_code_review_$(date).md`。
8. 报告：“完整代码库审查完成。X bugs、Y suggestions、Z nits。详见 <路径>。”

本计划完整、可执行、便于快速扫描。它复用了全部前期探索工作 + 官方审查基础设施。

## 计划状态
已准备好审查并调用 exit_plan_mode。（如需在范围/严重度阈值等方面做最终澄清，可使用 ask_user_question。）

## 修订说明（用户反馈）
- 计划全文已翻译为中文。
- 最终中文版审查计划 / 汇总文档需额外保存到 `docs/ver.202606.md`（仅中文）。
- 执行时：在生成 review 产物后，将中文版计划内容（或审查计划 + 关键发现汇总）复制/写入 `docs/ver.202606.md`（使用 write 工具）。此文件作为项目内可追溯的中文审查记录。
- plan.md 本身保留中文全文（作为会话内规范计划）。
