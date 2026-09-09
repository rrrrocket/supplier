# 核心数据字典

| 实体 | 业务含义 | 关键唯一性/归属 |
|---|---|---|
| `organizations` | 平台或供应商组织 | `code` 唯一；供应商数据隔离边界 |
| `users` | 组织内账号 | `email` 唯一，必须属于组织并拥有明确角色 |
| `supplier_profiles` | 企业主体与供应能力 | 每个供应商组织一条 |
| `supplier_applications` | 未入驻企业的公开申请与审核结果 | `application_no` 唯一；通过后关联组织与审核人 |
| `brands` | 规范化品牌主数据 | `code`、`normalized_name` 分别唯一；名称最长 160 个 Unicode 字符 |
| `supplier_brand_cooperations` | 平台确认的供应商—品牌正式合作关系 | 同一供应商 + 品牌同时最多一条 `ACTIVE`；保留历史模式 |
| `supplier_skus` | 不随成本、库存和交期变化的供应商货号身份 | 供应商 + `supplier_sku_code` 唯一；关联 Brand、Product 和可选 Variant |
| `products` | 商品是什么 | 创建组织 + `brand_id` + 型号 + 名称唯一；品牌展示名来自 Brand |
| `product_variants` | 商品规格/变体 | 属于 Product |
| `supplier_offers` | 某个 Supplier SKU 的当前供货条件 | `supplier_sku_id` 必填且唯一；不承担稳定 SKU 身份 |
| `inventory_snapshots` | 某次库存事实 | 属于 Supplier Offer，按时间累积 |
| `import_jobs` | 一次批量数据处理任务 | 属于组织，保留逐行结果 |
| `documents` | 营业执照、认证、报告等文件元数据 | 文件本体进入对象存储 |
| `event_logs` | 关键操作的审计记录 | 组织、Actor、Entity、事件与时间 |
| `integration_clients` | 外部系统的独立机器凭证 | `token_prefix` 唯一；仅保存哈希、scope、到期/启用状态和最近使用时间 |

## Supplier Application 审核字段

| 字段 | 说明 |
|---|---|
| `status` | `PENDING` / `APPROVED` / `REJECTED` |
| `review_notes` | 平台审核意见或驳回原因 |
| `reviewed_by_user_id` | 实际执行审核的平台管理员 |
| `reviewed_at` | 审核发生时间 |
| `approved_organization_id` | 通过审核后创建的供应商组织 |

审核通过同时创建 `Organization`、`SupplierProfile` 和 `SUPPLIER` 用户。临时密码只在创建响应中出现，不写入明文数据库。

## Brand、Supplier SKU 与 Offer 语义

| 字段 | 说明 |
|---|---|
| `products.brand_id` | 必填 FK → `brands.id`；最终数据库没有历史 `products.brand` 文本列 |
| `supplier_skus.id` | 对外稳定 `supplier_sku_id`；成本或供货条件变化不得改变 |
| `supplier_skus.supplier_sku_code` | 供应商自己稳定使用的货号；在一个供应商内唯一 |
| `supplier_skus.brand_id` / `product_id` | 必填且必须与供应商所有权、Product 品牌一致 |
| `supplier_offers.supplier_sku_id` | 必填且唯一 FK → `supplier_skus.id`；最终数据库没有历史 `supplier_offers.supplier_sku` 列 |
| `price` | 当前可执行供货价，不是零售价 |
| `currency` | 供货价币种，如 CNY、USD |
| `moq` | 当前供货条件下最小起订量 |
| `stock_qty` | 当前可承诺库存；无法承诺时不能随意填大数 |
| `lead_time_days` | 从确认订单到可发货的正常天数 |
| `fulfillment_mode` | `PURCHASE` / `DROPSHIP` / `CONSIGNMENT` / `JOINT_OPERATION` |
| `status` | 只有 `ACTIVE` 报价可参与后续匹配与执行 |

导入工作簿继续接受名为 `supplier_sku` 的输入列，但它只属于文件格式映射，导入时写入 `supplier_skus.supplier_sku_code`。Offer 创建 API 使用 `supplier_sku_code`，响应同时给出 `supplier_sku_id` 和 `supplier_sku_code`。

## Integration Client 与公共同步契约

| 字段/规则 | 说明 |
|---|---|
| `token_prefix` / `token_hash` | 前缀只用于定位候选，认证比较哈希；完整令牌只在创建/轮换时展示一次 |
| `scopes` | `suppliers:read`、`supplier-brands:read`、`supplier-skus:read`、`supplier-costs:read` |
| `expires_at` / `is_active` | 到期、轮换旧值或停用后立即拒绝；`last_used_at` 记录最近认证使用 |
| 集成供应商有效性 | 成本查询要求 `organizations.organization_type=SUPPLIER`、组织 `is_active=true`、对应 `supplier_profiles` 存在且 `status=APPROVED`；档案缺失或非 `APPROVED` 均为 `SUPPLIER_INACTIVE` |
| 列表分页 | `updated_since`、绑定查询语义与固定快照的不可解析 `cursor`、每页 `sync_watermark`、`include_inactive`、`limit` 1..500（默认 100） |
| 失效孤儿 SKU | `include_inactive=true` 时返回 `status=INACTIVE`、`commercial_mode=null` |
| 批量成本 | 1..500 行；`client_sku_id` 只在请求/响应回传，不持久化 |
| 限流 | 单 worker 进程内每客户端默认 600 次/60 秒；429 带整数秒 `Retry-After` |
| 成本审计 | 以 Integration Client 为 Actor，记录 `X-Request-ID`、路径和计数，不记录令牌、成本值或 `client_sku_id` |

## 数据原则

1. 原始数据不能被标准化或 AI 结果覆盖；
2. 商品、报价、库存和交易事实分开；
3. 历史报价和库存变化应保留；
4. 客户端不得决定数据所属组织；
5. 平台管理员和供应商角色必须隔离；
6. 临时密码只返回一次，数据库仅存密码哈希；
7. AI 只能提出建议，关键业务动作由确定性服务执行并写审计事件；
8. 认证、出口资质和产品参数必须有来源，不得由模型补造。
9. 正式品牌合作模式由平台管理；供应商申报的 `cooperation_modes` 仅表示意向。
10. 外部系统在自身数据库保存 `supplier_network_supplier_id`、`supplier_network_sku_id` 和人工确认映射；Supplier Network 不保存调用方 SKU 主数据。
