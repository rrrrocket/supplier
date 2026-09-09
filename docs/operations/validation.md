# 验证报告

本版本于 2026-09-09 完成以下本地验证：

| 检查项 | 结果 |
|---|---|
| `start.sh` Shell 语法 | 通过 |
| Python 模块编译 | 通过 |
| JavaScript 语法检查 | 通过 |
| 5 个 HTML 页面重复 ID 与本地资源检查 | 通过 |
| PostgreSQL 16 隔离测试环境 | 持久命名卷；迁移到 Alembic head，通过；数据库端口 6432 |
| Pytest 自动化测试 | 243 项通过 |
| 前端 Node 测试 | 52 项通过，0 失败 |
| 测试卷复用 | 完整与 focused 验证均复用 `supplier-tests` 的持久 PostgreSQL 服务、网络和命名卷；仅 one-shot runner 被移除 |
| 测试数据库最终状态 | `supplier-tests-test-db-1` 保持 healthy |
| 已初始化业务卷密码保护 | `.env` 缺失或密码为占位值时停止启动并提示恢复原配置；未初始化卷才生成密码 |
| Excel 解析错误边界 | 损坏、加密、扩展名与内容不符及截断 OLE Compound Document 的 XLSX/XLS，在扫描和配置预览均返回安全的 400 |
| 工作簿资源保护 | XLSX ZIP 条目、展开总量、单条目和压缩比受限；XLSX 不信任声明 dimension，按实际迭代行执行 Sheet/行/列/单元格预算；扫描只保留 20 行候选和 5 行样例 |
| 最终多 Sheet 来源校验 | 提交配置与上传工作簿重新核对；included 行来源必须属于选中 Sheet；legacy flat rows 保持兼容 |
| 10,000 行最终请求传输 | 使用与前端一致的完整 nested 结构通过 8 MiB 单字段限制；10,000 行接受且产生成功记录，10,001 行拒绝，excluded 行不计数 |
| 最终导入请求资源保护 | 上传文件以不超过 1 MiB 的分块读取并限制为 10 MiB；单字段限制 8 MiB；完整 multipart 请求限制 20 MiB |
| 反向代理导入容量 | Nginx `client_max_body_size` 为 24 MiB，高于应用层 20 MiB 完整请求上限 |
| 真实工作簿扫描 | 文件名正确；活动页 `Sheet1`；Sheet 列表为 `Sheet1`、`Sheet2`、`618Trumpeter` |
| `Sheet1` 独立配置 | 表头行 1；列映射 C/E/N/O/P/R |
| `Sheet1` 标准化结果 | 3,694 行；首行必填字段非空且成本为正；来源坐标保留为 `Sheet1:2` |
| 原工作簿字节保持 | 验收前后 SHA-256 均为 `451082f041c936809e9be77c4df681733cb8e3366ce327531458d06b51b85479` |
| 全新 PostgreSQL 16 数据库执行 Alembic `upgrade head` | 通过；当前唯一 head 为 `cc83f7e534a1` |
| PostgreSQL 历史供应商角色迁移 | 通过 |
| 最终供应商目录迁移 | 通过；`products.brand_id`、`supplier_offers.supplier_sku_id` 非空，历史文本列不存在，既有 ID/报价/库存关系保持 |
| Alembic 模型一致性 `check` | 无待生成迁移 |
| 通用集成 OpenAPI 契约 | 6 条 caller-neutral 路径的方法、schema、Bearer security、scope、成本错误码与精确响应集合通过运行时契约测试；列表无效 cursor/批量结构为 400，只有三个含受约束查询参数的列表发布 422，401 声明 `WWW-Authenticate`，429 声明 `Retry-After`，供应商详情与两条成本操作不发布不可达的自动 422；schema 先在局部构建并规范化再一次性发布，并发调用只得到同一规范化对象，失败时不残留 cache 且可重试，production reload 的 OpenAPI/docs 真实请求通过 |
| FastAPI 真实启动 | 通过 |
| `./start.sh status` | app 与 db 均为 healthy |
| `/api/health` | `{"status":"ok","service":"supplier-network","environment":"development"}` |
| PostgreSQL `SHOW port` | `6432` |
| `/`、`/apply`、`/login`、`/app`、`/admin`、`/api/docs` | 全部 HTTP 200 |
| 平台管理员登录与待审核申请读取 | 通过 |

## 自动化测试覆盖

- 密码哈希验证；
- 未登录访问保护；
- 供应商登录与看板；
- 公开入驻申请；
- 商品与供应报价创建；
- CSV 部分成功导入；
- XLSX/XLS 工作簿扫描、活动 Sheet 与独立 Sheet 配置；
- 腾讯文档空 Fill 的内存修复与源字节保持；
- 损坏、截断 OLE、加密、扩展名伪装和高展开量工作簿的安全拒绝；
- 伪造/缺失 XLSX dimension、实际 Sheet/行/列/单元格预算和单遍流式扫描；
- 多 Sheet 合并预览、10,000 行总上限和来源坐标；
- 最终导入的 Sheet 配置/来源归属，以及真实完整 payload 的 10,000/10,001/excluded 传输与业务边界；
- included 行重复 SKU 的服务端阻断与排除后导入；
- 需修正行筛选、单行/批量排除、排除计数和无删除恢复；
- 导入预览 50 行分页、120 行跨页编辑和完整列表/Sheet 配置提交；
- Product/Offer 以 500 行分块拉取 1,792 行完整数据、50 行 UI 分页、跨页编辑和筛选隔离；
- 文件/配置切换（含无效新文件）时陈旧异步响应隔离；
- 供应商无法访问平台管理 API；
- 平台管理员无法误用供应商业务 API；
- 管理员审核通过、组织开户与新账号登录；
- 管理员驳回与防止重复审核；
- Brand、正式供应商—品牌合作、稳定 Supplier SKU 和最终无 legacy 列迁移链；
- Integration Client 一次性令牌、哈希存储、scope、到期、轮换、停用、连接生命周期与权限隔离；
- 供应商/品牌/Supplier SKU 的增量 cursor 分页、`include_inactive` 及孤儿 SKU 的 nullable `commercial_mode`；
- 单个/1..500 行批量成本查询、供应商组织与 `SupplierProfile=APPROVED` 资格、8 个业务错误码、`X-Request-ID` 脱敏聚合审计与 600/60 限流。

## 尚未执行

- 真实 DNS、HTTPS 与云服务器部署；
- 跨浏览器视觉回归测试；
- PostgreSQL 高并发、压力和故障恢复测试；
- Task 8 的真实业务库备份/迁移和真实 Integration Client 凭证演练（需单独授权）；
- 与外部业务系统的线上联调。

## 已知非阻断警告

- 测试仍报告 Starlette `anyio.abc.BlockingPortal` 弃用警告；不影响本次 243 项 Python 测试与 52 项 Node 测试通过。
