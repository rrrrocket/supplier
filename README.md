# Matrix One Supplier Network

`https://supplier.matrix-one.tech` 的第一阶段可运行 MVP，用于建立中国供应网络。

它不是普通企业展示站，而是把分散供应能力转化为可管理、可比较、可同步的数据入口：

- 公开供应商入驻申请
- 平台管理员审核、驳回与组织开户
- 审核通过后自动创建供应商组织、企业档案和管理员账号
- 供应商账号登录与组织数据隔离
- 企业供应能力档案
- 统一商品主数据（Product）
- 独立供应报价（Supplier Offer）
- 价格、MOQ、库存、交期与履约方式
- CSV 批量导入、校验与 Upsert
- 库存快照
- 关键操作事件审计
- 自动生成 OpenAPI 文档

## 1. 本地启动

```bash
cd supplier
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env
uvicorn app.main:app --reload --port 8000
```

在 macOS 上也可以双击项目根目录的 `start-macos.command`，脚本会创建虚拟环境、安装依赖并打开登录页。

打开：

- 首页：`http://127.0.0.1:8000`
- 入驻申请：`http://127.0.0.1:8000/apply`
- 统一登录：`http://127.0.0.1:8000/login`
- 供应商工作台：`http://127.0.0.1:8000/app`
- 平台审核端：`http://127.0.0.1:8000/admin`
- API 文档：`http://127.0.0.1:8000/api/docs`

本地演示账号：

```text
供应商管理员
supplier@matrix-one.tech
MatrixOne123!

平台管理员
admin@matrix-one.tech
MatrixAdmin123!
```

演示数据在首次启动时自动生成，并包含一条待审核申请。生产环境必须设置 `SEED_DEMO_DATA=false`，替换 `SESSION_SECRET`，并使用真实账号初始化流程。

## 2. 完整业务体验

### 平台侧

1. 打开 `/apply` 提交一条新供应商申请；
2. 使用平台管理员账号登录；
3. 在 `/admin` 查看并审核申请；
4. 审核通过时复制系统生成的组织编码、登录邮箱与一次性临时密码；
5. 在“入驻供应商”查看新组织的数据沉淀情况。

临时密码只在审核通过的响应中返回一次。当前 MVP 尚未接入邮件邀请与自助密码重置，生产开放前必须补齐。

### 供应商侧

1. 使用供应商账号登录；
2. 完善企业与供应能力资料；
3. 创建商品主数据或进入“批量导入”；
4. 下载并填写标准 CSV 模板；
5. 上传商品、供应商 SKU、报价、库存、MOQ 和交期；
6. 查看商品、报价、库存快照与审计事件。

同一组织内，`供应商 SKU` 是供应报价的唯一更新键。再次导入同一 SKU 时会更新报价，而不是重复创建。

## 3. 当前技术结构

```text
FastAPI
├─ API-first 业务接口
├─ Session 登录与角色权限
├─ SQLAlchemy 2 数据模型
├─ SQLite 本地开发
├─ PostgreSQL 生产配置
├─ Alembic 数据库迁移
└─ 无构建依赖的响应式 Web UI
```

当前使用无构建前端，目的是让第一版在没有 Node 依赖时立即运行并验证业务。API 与数据模型保持独立，未来可以替换为 Next.js/React 前端，而无需重写核心业务。

## 4. 目录

```text
app/
├─ api/          路由、认证依赖、平台审核与 API 契约
├─ core/         配置与密码安全
├─ db/           数据库会话和幂等演示数据
├─ models/       核心业务实体
├─ schemas/      Pydantic 输入输出模型
├─ services/     事件、评分和看板逻辑
└─ web/          公开站、供应商门户与平台审核 UI
migrations/      Alembic 迁移
scripts/         开发与重置脚本
deploy/          Nginx / systemd 示例
tests/           API、权限、安全与审核闭环测试
```

## 5. 核心边界

- **Supplier Application**：未入驻企业的公开申请；审核通过后关联新组织。
- **Organization**：平台或供应商的数据隔离边界。
- **Product**：描述商品是什么；不直接存供应商价格和库存。
- **Supplier Offer**：描述某供应商在特定时间能以什么价格、MOQ、库存和交期供货。
- **Inventory Snapshot**：保留库存变化事实。
- **Event Log**：记录谁在什么时候对什么实体执行了什么操作。
- **Organization ID**：所有供应商业务数据按组织隔离，客户端不能自行指定数据归属。

详细说明见 [ARCHITECTURE.md](ARCHITECTURE.md) 和 [DATA_DICTIONARY.md](DATA_DICTIONARY.md)。

## 6. 测试与静态检查

```bash
pytest -q
python3 -m compileall app
node --check app/web/assets/common.js
node --check app/web/assets/login.js
node --check app/web/assets/apply.js
node --check app/web/assets/app.js
node --check app/web/assets/admin.js
```

## 7. 数据库迁移

```bash
alembic upgrade head
alembic revision --autogenerate -m "describe change"
alembic check
```

## 8. Docker + PostgreSQL

```bash
cp .env.example .env
export POSTGRES_PASSWORD='replace-me'
export SESSION_SECRET='replace-with-a-long-random-secret'
docker compose up -d --build
```

服务默认只映射到 `127.0.0.1:8000`，由 Nginx 反向代理到：

```text
supplier.matrix-one.tech
```

Nginx 示例见 `deploy/nginx-supplier.conf`。配置 DNS、HTTPS 证书、真实平台管理员、数据库备份和错误监控后再开放公网。

## 9. 生产上线前必须完成

- 关闭演示数据并建立安全的管理员初始化方式；
- 接入邮件邀请、密码设置/重置和账号生命周期；
- 接入营业执照、产品认证与对象存储；
- 增加申请补充材料和多级审核能力；
- 增加限流、防暴力登录、会话撤销与更完整安全审计；
- 配置 HTTPS、数据库备份、错误监控、日志脱敏和审计保留周期；
- 与现有 ERP 确定 Product、Offer、Inventory、Transaction 的主数据归属与同步协议。
