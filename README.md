# Matrix One Supplier Network

`https://supplier.matrix-one.tech` 的第一阶段可运行 MVP，用于建立中国供应网络。

它不是普通企业展示站，而是把分散供应能力转化为可管理、可比较、可同步的数据入口：

- 公开供应商入驻申请
- 平台管理员审核、驳回与组织开户
- 审核通过后自动创建供应商组织、企业档案和供应商账号
- 供应商账号登录与组织数据隔离
- 企业供应能力档案
- 统一商品主数据（Product）
- 独立供应报价（Supplier Offer）
- 价格、MOQ、库存、交期与履约方式
- CSV / XLSX / XLS / PDF 智能表格导入、字段匹配、预览校验与 Upsert
- 库存快照
- 关键操作事件审计
- 自动生成 OpenAPI 文档

## 1. 一键启动

本地开发与服务器使用相同的 PostgreSQL 容器化环境。预先安装 Docker Engine 和 Docker Compose 插件，进入项目目录后执行：

```bash
./start.sh
```

脚本会自动：

- 检查 Docker 与 Compose；
- 创建 `.env` 并生成数据库密码、Session 密钥和管理员密码；
- 构建应用镜像；
- 启动 PostgreSQL 与 FastAPI；
- 执行 Alembic 数据库迁移；
- 等待应用健康检查通过。

常用运维命令：

```bash
./start.sh status
./start.sh logs
./start.sh restart
./start.sh stop
```

服务默认仅监听服务器的 `127.0.0.1:6790`，由 Nginx 反向代理。可在 `.env` 中修改 `APP_PORT`、`APP_URL`、`ALLOWED_HOSTS` 和 `BIND_ADDRESS`。
PostgreSQL 在 Compose 内部统一监听 `6432`，生产与测试配置一致。

访问地址：

- 首页：`http://127.0.0.1:6790`
- 入驻申请：`http://127.0.0.1:6790/apply`
- 统一登录：`http://127.0.0.1:6790/login`
- 供应商工作台：`http://127.0.0.1:6790/app`
- 平台审核端：`http://127.0.0.1:6790/admin`
- API 文档：`http://127.0.0.1:6790/api/docs`

平台管理员账号固定配置在 `.env`：

```dotenv
ADMIN_EMAIL=admin@your-company.com
ADMIN_PASSWORD=replace-with-a-strong-password
ADMIN_NAME=平台管理员
```

应用启动时自动创建或同步该管理员；修改配置密码并重启后，登录密码会同步更新。`.env` 不会提交到 Git。供应商账号通过公开申请和平台审核流程创建。

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
3. 创建商品主数据或进入“智能表格导入”；
4. 直接上传供应商原始 CSV、XLSX、XLS 或文本型 PDF 成本表；
5. 可用语言说明表头行、成本列、SKU、统一类目、币种和默认值；
6. 检查系统生成的字段映射与标准商品列表预览；
7. 确认后导入商品、供应商 SKU、报价、库存、MOQ 和交期；
8. 查看商品、报价、库存快照与审计事件。

语言说明示例：`第 3 行是表头；产品编码作为供应商 SKU；含税单价作为采购价；全部商品类目为工业自动化；币种人民币；默认交期 5 天。`

系统会优先根据说明匹配字段，再结合中英文常见表头自动识别。预览阶段不会写入数据，所有建议映射均可人工调整；目标列表支持编辑、新增和删除行，确认时严格按当前列表导入。

PDF 会优先提取表格并合并跨页同结构数据。纯扫描图片 PDF 为避免误读价格，需先完成 OCR 后再上传。

同一组织内，`供应商 SKU` 是供应报价的唯一更新键。再次导入同一 SKU 时会更新报价，而不是重复创建。

## 3. 当前技术结构

```text
FastAPI
├─ API-first 业务接口
├─ Session 登录与角色权限
├─ SQLAlchemy 2 数据模型
├─ PostgreSQL 统一数据存储
├─ Alembic 数据库迁移
└─ 无构建依赖的响应式 Web UI
```

当前使用无构建前端，目的是让第一版在没有 Node 依赖时立即运行并验证业务。API 与数据模型保持独立，未来可以替换为 Next.js/React 前端，而无需重写核心业务。

## 4. 目录

```text
app/
├─ api/          路由、认证依赖、平台审核与 API 契约
├─ core/         配置与密码安全
├─ db/           数据库基础模型和会话管理
├─ models/       核心业务实体
├─ schemas/      Pydantic 输入输出模型
├─ services/     事件、评分和看板逻辑
└─ web/          公开站、供应商门户与平台审核 UI
migrations/      Alembic 迁移
deploy/          Nginx 示例
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

详细说明见 [文档索引](docs/README.md)、[系统架构](docs/architecture/overview.md) 和 [数据字典](docs/architecture/data-dictionary.md)。

## 6. 测试与静态检查

```bash
./start.sh test
```

Python 测试在独立的 PostgreSQL 16 临时容器中执行，不连接业务数据库；同一命令也会完成前端脚本语法检查和登录状态测试。测试容器、网络和临时数据库会在结束后自动删除。

## 7. 数据库迁移

```bash
docker compose exec app alembic current
docker compose exec app alembic check
```

`./start.sh` 每次启动应用前都会自动执行 `alembic upgrade head`。

## 8. PostgreSQL 运行环境

```bash
./start.sh
```

服务默认只映射到 `127.0.0.1:6790`，由 Nginx 反向代理到：

```text
supplier.matrix-one.tech
```

Nginx 示例见 `deploy/nginx-supplier.conf`。配置 DNS、HTTPS 证书、真实平台管理员、数据库备份和错误监控后再开放公网。

## 9. 生产上线前必须完成

- 创建并妥善保管首个平台管理员账号；
- 接入邮件邀请、密码设置/重置和账号生命周期；
- 接入营业执照、产品认证与对象存储；
- 增加申请补充材料和多级审核能力；
- 增加限流、防暴力登录、会话撤销与更完整安全审计；
- 配置 HTTPS、数据库备份、错误监控、日志脱敏和审计保留周期；
- 与外部业务系统确定 Product、Offer、Inventory、Transaction 的主数据归属与同步协议。
