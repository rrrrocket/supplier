# 核心数据字典

| 实体 | 业务含义 | 关键唯一性/归属 |
|---|---|---|
| `organizations` | 平台或供应商组织 | `code` 唯一；供应商数据隔离边界 |
| `users` | 组织内账号 | `email` 唯一，必须属于组织并拥有明确角色 |
| `supplier_profiles` | 企业主体与供应能力 | 每个供应商组织一条 |
| `supplier_applications` | 未入驻企业的公开申请与审核结果 | `application_no` 唯一；通过后关联组织与审核人 |
| `products` | 商品是什么 | 当前按创建组织 + 品牌 + 型号 + 名称去重 |
| `product_variants` | 商品规格/变体 | 属于 Product |
| `supplier_offers` | 某供应商的实际供货条件 | 组织 + `supplier_sku` 唯一 |
| `inventory_snapshots` | 某次库存事实 | 属于 Supplier Offer，按时间累积 |
| `import_jobs` | 一次批量数据处理任务 | 属于组织，保留逐行结果 |
| `documents` | 营业执照、认证、报告等文件元数据 | 文件本体进入对象存储 |
| `event_logs` | 关键操作的审计记录 | 组织、Actor、Entity、事件与时间 |

## Supplier Application 审核字段

| 字段 | 说明 |
|---|---|
| `status` | `PENDING` / `APPROVED` / `REJECTED` |
| `review_notes` | 平台审核意见或驳回原因 |
| `reviewed_by_user_id` | 实际执行审核的平台管理员 |
| `reviewed_at` | 审核发生时间 |
| `approved_organization_id` | 通过审核后创建的供应商组织 |

审核通过同时创建 `Organization`、`SupplierProfile` 和 `SUPPLIER` 用户。临时密码只在创建响应中出现，不写入明文数据库。

## Supplier Offer 必填语义

| 字段 | 说明 |
|---|---|
| `supplier_sku` | 供应商自己稳定使用的唯一货号，不应随渠道变化 |
| `price` | 当前可执行供货价，不是零售价 |
| `currency` | 供货价币种，如 CNY、USD |
| `moq` | 当前供货条件下最小起订量 |
| `stock_qty` | 当前可承诺库存；无法承诺时不能随意填大数 |
| `lead_time_days` | 从确认订单到可发货的正常天数 |
| `fulfillment_mode` | `PURCHASE` / `DROPSHIP` / `CONSIGNMENT` / `JOINT_OPERATION` |
| `status` | 只有 `ACTIVE` 报价可参与后续匹配与执行 |

## 数据原则

1. 原始数据不能被标准化或 AI 结果覆盖；
2. 商品、报价、库存和交易事实分开；
3. 历史报价和库存变化应保留；
4. 客户端不得决定数据所属组织；
5. 平台管理员和供应商角色必须隔离；
6. 临时密码只返回一次，数据库仅存密码哈希；
7. AI 只能提出建议，关键业务动作由确定性服务执行并写审计事件；
8. 认证、出口资质和产品参数必须有来源，不得由模型补造。
