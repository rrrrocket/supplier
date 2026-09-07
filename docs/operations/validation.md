# 验证报告

本版本于 2026-09-08 完成以下本地验证：

| 检查项 | 结果 |
|---|---|
| `start.sh` Shell 语法 | 通过 |
| Python 模块编译 | 通过 |
| JavaScript 语法检查 | 通过 |
| 5 个 HTML 页面重复 ID 与本地资源检查 | 通过 |
| PostgreSQL 16 隔离测试环境 | 持久命名卷；迁移到 Alembic head，通过；数据库端口 6432 |
| 连续两次 Pytest 自动化测试 | 每次 56 项通过 |
| 连续两次前端 Node 测试 | 每次 21 项通过，0 失败 |
| 测试卷复用 | `supplier-tests_supplier_test_postgres:2026-09-07T20:40:00Z` 两次相同 |
| 测试数据库最终状态 | `supplier-tests-test-db-1` 保持 healthy |
| 真实工作簿扫描 | 文件名正确；活动页 `Sheet1`；Sheet 列表为 `Sheet1`、`Sheet2`、`618Trumpeter` |
| `Sheet1` 独立配置 | 表头行 1；列映射 C/E/N/O/P/R |
| `Sheet1` 标准化结果 | 3,694 行；首行必填字段非空且成本为正；来源坐标保留为 `Sheet1:2` |
| 原工作簿字节保持 | 验收前后 SHA-256 均为 `451082f041c936809e9be77c4df681733cb8e3366ce327531458d06b51b85479` |
| 全新 PostgreSQL 16 数据库执行 Alembic `upgrade head` | 通过 |
| PostgreSQL 历史供应商角色迁移 | 通过 |
| Alembic 模型一致性 `check` | 无待生成迁移 |
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
- 多 Sheet 合并预览、10,000 行总上限和来源坐标；
- included 行重复 SKU 的服务端阻断与排除后导入；
- 50 行分页、跨页状态和完整列表提交；
- 文件/配置切换时陈旧异步响应隔离；
- 供应商无法访问平台管理 API；
- 平台管理员无法误用供应商业务 API；
- 管理员审核通过、组织开户与新账号登录；
- 管理员驳回与防止重复审核。

## 尚未执行

- 真实 DNS、HTTPS 与云服务器部署；
- 跨浏览器视觉回归测试；
- PostgreSQL 高并发、压力和故障恢复测试；
- 与外部业务系统的线上联调。

## 已知非阻断警告

- 测试仍报告 Starlette `anyio.abc.BlockingPortal` 弃用警告；不影响本次 56 项 Python 测试与 21 项 Node 测试通过。
