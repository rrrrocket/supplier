# 验证报告

本版本完成以下本地验证：

| 检查项 | 结果 |
|---|---|
| `start.sh` Shell 语法 | 通过 |
| Python 模块编译 | 通过 |
| JavaScript 语法检查 | 通过 |
| 5 个 HTML 页面重复 ID 与本地资源检查 | 通过 |
| PostgreSQL 16 隔离测试环境 | 持久命名卷；迁移到 Alembic head，通过；数据库端口 6432 |
| 连续两次 Pytest 自动化测试 | 每次 30 项通过 |
| 连续两次前端登录状态测试 | 每次 11 项通过 |
| 测试卷复用 | `supplier-tests_supplier_test_postgres:2026-09-07T20:40:00Z` 两次相同 |
| 测试用户数据保留 | 第一次 8 行，第二次 11 行，未减少 |
| 测试数据库最终状态 | `supplier-tests-test-db-1` 保持 healthy |
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
- 供应商无法访问平台管理 API；
- 平台管理员无法误用供应商业务 API；
- 管理员审核通过、组织开户与新账号登录；
- 管理员驳回与防止重复审核。

## 尚未执行

- 真实 DNS、HTTPS 与云服务器部署；
- 跨浏览器视觉回归测试；
- PostgreSQL 高并发、压力和故障恢复测试；
- 与外部业务系统的线上联调。
