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
│  ├─ ProductVariant
│  └─ SupplierOffer
│     └─ InventorySnapshot
├─ ImportJob
├─ Document
└─ EventLog

SupplierApplication
├─ reviewed_by_user_id → Platform Admin
└─ approved_organization_id → Supplier Organization
```

### Product 与 Offer 分离

`Product` 回答“这是什么商品”；`SupplierOffer` 回答“谁能以什么条件提供”。同一 Product 后续允许关联多个供应商报价，不能把成本和库存直接写死在商品表中。

### Organization 是第一层隔离边界

每个供应商组织拥有自己的用户、商品、报价、导入记录、文件与事件。所有受保护 API 均从登录 Session 获取组织，不接受客户端自由传入 `organization_id`。

平台管理员属于独立 PLATFORM 组织，仅通过受控管理 API 审核申请和查看组织级汇总；供应商账号无法访问管理 API。

### Event Log 是审计与未来 AI 学习基础

当前已记录：

- 用户登录/退出
- 企业资料更新
- 商品创建
- 报价创建/更新
- CSV 导入
- 供应商申请通过/驳回

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
Product 标准化
  ↓
Supplier Offer Upsert
  ↓
Inventory Snapshot
  ↓
Event Log
  ↓
外部系统同步 / Matching Engine
```

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
