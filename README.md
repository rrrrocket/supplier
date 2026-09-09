# Matrix One Supplier Network

`https://supplier.matrix-one.tech` 的第一阶段可运行 MVP，用于建立中国供应网络。

它不是普通企业展示站，而是把分散供应能力转化为可管理、可比较、可同步的数据入口：

- 公开供应商入驻申请
- 平台管理员审核、驳回与组织开户
- 审核通过后自动创建供应商组织、企业档案和供应商账号
- 供应商账号登录与组织数据隔离
- 企业供应能力档案
- 统一商品主数据（Product）
- 规范化品牌、平台确认的供应商—品牌合作模式
- 稳定 Supplier SKU 身份与独立供应报价（Supplier Offer）
- 价格、MOQ、库存、交期与履约方式
- CSV / XLSX / XLS / PDF 智能表格导入、字段匹配、预览校验与 Upsert
- 库存快照
- 关键操作事件审计
- 独立 Integration Client、scope、轮换/停用和默认 600 次/60 秒限流
- `/api/integrations/v1` 通用供应商、品牌、SKU 和模式 A 成本接口
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
5. Excel 文件会先扫描工作簿并默认选择活动 Sheet；可继续单选、多选或全选 Sheet；
6. 为每个选中 Sheet 分别确认表头行、字段映射和默认值；
7. 检查合并后的标准商品列表；页面每次渲染 50 行，翻页和编辑始终作用于完整预览数据；
8. 按需筛选需修正行并批量排除；排除只改变 `included` 状态，可一键恢复且不会删除原行；也可逐行修改供应商 SKU，所有已包含行的重复 SKU 冲突解决后才能确认导入；
9. 确认后提交完整的已编辑列表，导入商品、供应商 SKU、报价、库存、MOQ 和交期；
10. 查看商品、报价、库存快照与审计事件。

语言说明示例：`第 3 行是表头；产品编码作为供应商 SKU；含税单价作为采购价；全部商品类目为工业自动化；币种人民币；默认交期 5 天。`

系统会优先根据说明匹配字段，再结合中英文常见表头自动识别。预览阶段不会写入数据，所有建议映射均可人工调整；目标列表支持编辑、新增和删除行，确认时严格按当前列表导入。

当前 `Sheet1` 验收示例使用 Excel 列字母作为稳定映射，不依赖可能为空或重复的表头：

| Excel 列 | 目标字段 |
|---|---|
| C | 供应商 SKU |
| E | 商品名称 |
| N | 品牌 |
| O | 型号/比例 |
| P | 类目 |
| R | 成本价 |

Excel 多 Sheet 流程会把每行的来源 Sheet 和原始行号带入预览及错误信息。CSV、TSV、TXT 和 PDF 继续使用原有单数据源识别流程。

PDF 会优先提取表格并合并跨页同结构数据。纯扫描图片 PDF 为避免误读价格，需先完成 OCR 后再上传。

同一组织内，`supplier_sku_code` 是稳定 Supplier SKU 的业务唯一键。再次导入同一货号时复用相同 `supplier_sku_id` 并更新当前报价，而不是重复创建。工作簿中的 `supplier_sku` 是兼容输入列名，不是最终数据库列或 Offer API 字段。

## 3. 当前技术结构

```text
FastAPI
├─ API-first 业务接口
├─ Session 登录与角色权限
├─ Integration Client Bearer 认证与 scope
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
- **Brand / Supplier Brand Cooperation**：规范化品牌，以及由平台确认的当前/历史正式合作模式。
- **Supplier SKU**：供应商货号的稳定身份；成本、库存和交期变化不改变 ID。
- **Supplier Offer**：描述一个 Supplier SKU 当前能以什么价格、MOQ、库存和交期供货。
- **Inventory Snapshot**：保留库存变化事实。
- **Event Log**：记录谁在什么时候对什么实体执行了什么操作。
- **Integration Client**：外部系统独立机器凭证；明文令牌只展示一次，数据库只保存哈希。
- **Organization ID**：所有供应商业务数据按组织隔离，客户端不能自行指定数据归属。

通用集成接口统一使用 `/api/integrations/v1`，提供六条供应商/品牌/Supplier SKU/成本路径。列表支持 `updated_since`、绑定查询条件与固定快照的 `cursor`、每页 `sync_watermark`、`include_inactive` 和 1..500 的 `limit`；批量成本接受 1..500 行并原样回传调用方的 `client_sku_id`。完整接入契约见 [通用系统接入指南](docs/integrations/system-integration-guide.md)。

详细说明见 [文档索引](docs/README.md)、[系统架构](docs/architecture/overview.md) 和 [数据字典](docs/architecture/data-dictionary.md)。

## 6. 测试与静态检查

```bash
./start.sh test
```

Python 测试在独立的 PostgreSQL 16 服务和持久命名卷中执行，使用固定测试数据库与凭证，且不连接业务数据库；同一命令也会完成前端脚本语法检查和登录状态测试。每次运行只移除一次性的测试 runner，保留健康的 `test-db`、测试网络和命名卷；测试会话在数据库名必须以 `_test` 结尾的硬保护下清空业务表，避免历史 fixture 累积。测试 Compose 不开放 Web 或数据库宿主机端口。

## 7. 数据库迁移

`./start.sh` 和 `./start.sh restart` 都会在应用启动前自动执行现有 Alembic 升级。当前 Alembic head 是 `cc83f7e534a1`；最终表只保留非空 `products.brand_id` 和 `supplier_offers.supplier_sku_id`，不再保留对应的历史文本列。

该迁移链只支持停机发布，不支持跨 `cc83f7e534a1` 的滚动升级：

1. 停止并确认所有旧版应用、导入任务和其他数据库 writer 已退出；
2. 创建可恢复的数据库备份，并在只读检查中确认 Offer 组织、Product owner/brand、Variant 和 Supplier SKU 的域关系一致；
3. 在停写窗口执行 `alembic upgrade head`；任一 preflight 报错时保持旧版停机，修正或恢复数据后重试；
4. 升级成功后只启动最终二进制，再执行健康检查和抽样校验。

`cc83f7e534a1` 删除旧文本列后，不能直接回滚到旧二进制。回滚必须先执行经过验证的数据库 downgrade，或恢复发布前备份，再启动旧版。过渡期 reconciliation 只能收敛迁移执行前的迟到写入，不能替代上述停写窗口。

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
- 若改为多 Uvicorn worker 或多实例部署，将当前进程内 Integration Client 限流器替换为共享网关或共享数据存储限流器；
- 与外部业务系统确定 Product、Offer、Inventory、Transaction 的主数据归属与同步协议。
