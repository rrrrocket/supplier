# 架构说明

## 1. 系统定位

Supplier Network 是 Matrix One 整体体系中的 **Supply Acquisition Layer**：

```text
中国供应商
   ↓
Supplier Network
   ↓
Product / Offer / Inventory / Capability
   ↓
业务执行系统 + Data / AI
   ↓
ToC Marketplace + ToB Trade
   ↓
真实交易与履约结果回流
```

它负责把分散、不可比较的中国供给转化为可调用数据。第一阶段不重复建设完整订单、财务和跨境履约系统。

## 2. 当前领域模型

```text
Organization
├─ User
├─ SupplierProfile
├─ Product
│  └─ ProductVariant
├─ SupplierSku ─ SupplierOffer ─ InventorySnapshot
├─ SupplierBrandCooperation ─ Brand
├─ ImportJob
├─ Document
└─ EventLog

IntegrationClient
└─ scoped bearer credential → /api/integrations/v1

SupplierApplication
├─ reviewed_by_user_id → Platform Admin
└─ approved_organization_id → Supplier Organization
```

### Product 与 Offer 分离

`Product` 回答“这是什么商品”；`SupplierSku` 提供不会随成本、库存或交期变化的供应商货号身份；`SupplierOffer` 回答“当前能以什么条件提供”。`Product.brand_id` 关联规范化 `Brand`，`SupplierOffer.supplier_sku_id` 关联稳定 SKU。最终数据库不再包含历史 `products.brand` 或 `supplier_offers.supplier_sku` 列。

### 品牌合作由平台确认

`SupplierBrandCooperation` 记录一个供应商与一个品牌的正式 `SELF_PURCHASE`、`JOINT_OPERATION` 或 `B2B` 模式，并保留失效历史。同一供应商和品牌同时最多一条有效关系。供应商申请里的合作方式只是意向；供应商可以查看正式关系，但只有平台管理员可以变更。

### Organization 是第一层隔离边界

每个供应商组织拥有自己的用户、商品、报价、导入记录、文件与事件。供应商业务 API 从登录 Session 获取组织，不接受客户端自由传入 `organization_id`。

平台管理员属于独立 PLATFORM 组织，仅通过受控管理 API 审核申请和查看组织级汇总；供应商账号无法访问管理 API。

通用集成 API 使用独立 `IntegrationClient` Bearer 令牌和 scope，不复用网页 Session。令牌明文只在创建或轮换时展示一次；数据库只保存哈希。外部系统只能读取平台已确认的供应商、品牌、SKU 和模式 A 当前成本，并在自己的数据库保存 `supplier_network_supplier_id`、`supplier_network_sku_id` 及人工确认的映射。

### Event Log 是审计与未来 AI 学习基础

当前已记录：

- 用户登录/退出
- 企业资料更新
- 商品创建
- 报价创建/更新
- CSV 导入
- 供应商申请通过/驳回
- 品牌合作关系变更
- Integration Client 创建、轮换和停用
- 通用成本查询的调用方、请求 ID、接口及成功/错误计数

后续扩展为：

```text
Decision → Approval → Action → Outcome
```

## 3. 分层

```text
Public / Supplier / Admin Web UI
  ↓
API / Schemas / Role Policy
  ↓
Application Services
  ↓
Domain Models
  ↓
SQLAlchemy / PostgreSQL
```

未来 AI Agent 只能通过受控 API 或 Tool Layer 操作业务，不允许直接修改核心数据库。

## 4. 与外部业务系统的边界

Supplier Network 保留：

- 供应商入驻与审核
- 供应能力档案
- 商品目录接入
- 供应报价、MOQ、库存和交期
- 资质与能力文件
- 供应商协同和通知

外部业务系统继续成为：

- 商品全局主数据与渠道 Listing
- 采购与补货
- ToC / ToB 订单
- 定价、利润、广告和履约执行
- 真实交易事实库

第一阶段 Supplier Network 暂时存 Product；正式整合前必须确定 Product 主键归属。长期推荐由外部业务系统生成全局 `product_id`，供应商门户通过 API 创建候选商品或关联既有 Product。

## 5. 当前数据流

### 入驻闭环

```text
公开申请
  ↓
平台管理员审核
  ├─ 驳回 → 保存审核理由与事件
  └─ 通过
       ↓
   创建 Supplier Organization
       ↓
   创建 Supplier Profile
       ↓
   创建 Supplier Account + 临时密码
       ↓
   供应商登录并完善资料
```

临时密码只返回一次。邮件邀请、首次设置密码与自助重置属于生产前必做能力。

### 商品与报价

```text
手工创建 / CSV 导入
  ↓
Brand + Product 标准化
  ↓
稳定 Supplier SKU 解析
  ↓
Supplier Offer Upsert
  ↓
Inventory Snapshot
  ↓
Event Log
  ↓
外部系统同步
```

供应商工作台用 `limit=500` 分块读取完整 Product/Offer 列表，在浏览器内每页渲染 50 行。导入预览的排除动作只切换行的 `included` 状态：需修正行可以批量排除和恢复，未包含行不参与重复校验或最终写入。

### 通用系统接入

```text
平台管理员创建 IntegrationClient（一次性令牌）
  ↓
Bearer 认证 + scope + 每客户端限流
  ↓
/api/integrations/v1
  ├─ 供应商/品牌/Supplier SKU 增量分页
  └─ 单个/批量模式 A 当前成本
  ↓
调用方保存稳定 ID 并完成人工映射
```

列表使用 `updated_since + cursor + limit + include_inactive`；成本批量一次 1..500 行。默认限流为每个 Integration Client 每 60 秒 600 次，429 返回 `Retry-After`。当前单 Uvicorn worker 使用进程内限流；多 worker 或多实例部署必须提供共享限流器。

### 后续供应商评分

```text
资料完整度
+ 报价响应
+ 库存准确率
+ 准时发货率
+ 质量问题率
+ 售后响应
+ 历史贡献利润
= Supplier Capability Score
```

在没有真实订单数据前，不生成虚假的综合供应商评分。

## 6. 技术演进

### 当前 MVP

- FastAPI
- SQLAlchemy 2
- PostgreSQL
- Alembic
- 服务端静态响应式 Web UI
- Session Cookie
- PLATFORM_ADMIN / SUPPLIER 角色边界

### 首批真实供应商试点后

- PostgreSQL 作为唯一业务数据库
- Redis 用于限流、缓存和短任务
- S3 兼容对象存储用于证书、目录和图片
- 异步队列处理大型导入与外部系统同步
- 邮件邀请与密码生命周期
- OpenTelemetry / Sentry 级监控

### 数据量明显增长后

- Transactional Outbox / Webhook
- 独立分析仓库
- 商品实体匹配、向量检索和 Product Graph
- Agent Tool Gateway

试点前不引入 Kafka、图数据库、多个搜索引擎或微服务拆分。
