# 供应商品牌、SKU 与通用系统集成设计

状态：已实现
日期：2026-09-09

## 1. 背景

一个供应商可以经营多个品牌，不同品牌可以采用不同合作模式。例如，同一供应商的品牌 A 使用自营采购，品牌 B 使用联营。经业务确认，同一供应商的同一品牌在同一时间不会同时使用多种合作模式。

Supplier Network 通过通用集成 API 服务多个外部业务系统。调用方保存 Supplier Network 的供应商和 SKU 稳定标识，在自己的系统内完成本地 SKU 与 Supplier SKU 的自动候选匹配和人工确认，然后从 Supplier Network 拉取模式 A SKU 的当前成本价。

## 2. 目标

- 支持一个供应商关联多个品牌，并为每个品牌确定唯一的当前合作模式。
- 为供应商货号建立独立、稳定的 `supplier_sku_id`。
- 将 SKU 稳定身份与会变化的价格、库存、MOQ 和交期分开。
- 允许调用方保存供应商和 SKU 的外部引用。
- 为模式 A SKU 提供“货号对应当前成本价”的简单查询接口。
- 保证模式 B、模式 C SKU 不通过成本接口泄露价格。
- 保留品牌合作模式、SKU 状态和成本变化的审计记录。

## 3. 非目标

- Supplier Network 不保存调用方 SKU 主数据。
- Supplier Network 不保存或确认调用方 SKU 与 Supplier SKU 的映射关系。
- 本期不计算采购单最终成本、入库成本、税费、运费或汇率成本。
- 本期不实现阶梯价、成本版本选择或历史时点成本查询。
- 本期不为任何调用方建立专属 URL；所有调用方使用同一套通用接口。
- 本期不实现 Webhook，先使用增量拉取和实时成本查询。

## 4. 系统边界

| 数据 | 主系统 | 说明 |
|---|---|---|
| 供应商主体 | Supplier Network | `supplier_id` 为供应商组织的稳定 UUID |
| 品牌及合作模式 | Supplier Network | 同一供应商、同一品牌仅一条当前有效关系 |
| Supplier SKU | Supplier Network | `supplier_sku_id` 永久稳定 |
| 当前供货信息和成本价 | Supplier Network | 模式 A 的当前 `price` 对外表达为 `cost_price` |
| 调用方 SKU | 调用方 | Supplier Network 不复制调用方内部主键 |
| 调用方 SKU 与 Supplier SKU 映射 | 调用方 | 自动生成候选，必须人工确认 |
| 采购、入库和最终成本 | 调用方 | 不由 Supplier Network 计算 |

## 5. 领域模型

### 5.1 Brand

品牌已从历史 `Product.brand` 字符串提升为独立主数据；最终数据库只保留 `products.brand_id`，API 仍把关联的 `Brand.name` 序列化为展示字段 `brand`。

| 字段 | 类型 | 约束/说明 |
|---|---|---|
| `id` | UUID | 主键 |
| `code` | String(60) | 唯一、稳定、便于运营识别 |
| `name` | String(160) | 品牌展示名称 |
| `normalized_name` | String(160) | 用于去重和匹配 |
| `aliases` | JSON array | 可选品牌别名 |
| `status` | String(30) | `ACTIVE` / `INACTIVE` |
| `created_at` / `updated_at` | timestamp | 审计时间 |

### 5.2 SupplierBrandCooperation

表示供应商与品牌之间的正式合作关系。

| 字段 | 类型 | 约束/说明 |
|---|---|---|
| `id` | UUID | 主键 |
| `supplier_id` | UUID | FK → `organizations.id`，组织类型必须是 `SUPPLIER` |
| `brand_id` | UUID | FK → `brands.id` |
| `commercial_mode` | String(40) | `SELF_PURCHASE` / `JOINT_OPERATION` / `B2B` |
| `status` | String(30) | `ACTIVE` / `INACTIVE` |
| `valid_from` / `valid_to` | date | 合作有效期，可为空 |
| `notes` | Text | 平台侧说明 |
| `created_at` / `updated_at` | timestamp | 审计时间 |

约束与规则：

- 同一 `supplier_id + brand_id` 只能存在一条 `ACTIVE` 记录。
- 合作模式改变时，将旧记录置为 `INACTIVE` 并创建新记录，不覆盖历史。
- 供应商入驻申请中的 `cooperation_modes` 仅作为申请意向，不作为正式执行依据。
- 正式合作关系由平台确认；供应商可以查看，但不能自行切换已生效模式。

### 5.3 SupplierSku

`SupplierSku` 是 Supplier Network 内稳定的供应商货号身份，不等同于报价记录。

| 字段 | 类型 | 约束/说明 |
|---|---|---|
| `id` | UUID | 稳定的 `supplier_sku_id` |
| `supplier_id` | UUID | FK → 供应商组织 |
| `brand_id` | UUID | FK → `brands.id` |
| `product_id` | UUID | FK → `products.id` |
| `variant_id` | UUID nullable | FK → `product_variants.id` |
| `supplier_sku_code` | String(120) | 供应商自己的货号 |
| `manufacturer_part_number` | String(160) nullable | 原厂型号/料号，用于匹配 |
| `barcode` | String(80) nullable | GTIN/EAN/UPC 等，用于匹配 |
| `status` | String(30) | `ACTIVE` / `INACTIVE` |
| `created_at` / `updated_at` | timestamp | 审计时间和增量同步依据 |

唯一性与隔离：

- `supplier_id + supplier_sku_code` 唯一。
- `SupplierSku.supplier_id` 必须与商品报价所属供应商一致。
- 成本查询通过 `supplier_id + brand_id` 解析当前有效的品牌合作关系；SKU 不直接绑定某一条可能失效的历史合作记录。
- SKU 停用时保留 ID，不删除已经被外部系统绑定的身份。
- 修改成本价、库存或交期不得改变 `supplier_sku_id`。

### 5.4 SupplierOffer

现有 `SupplierOffer` 继续保存当前可执行供货信息，但不再承担 SKU 稳定身份。

主要调整：

- 必填 `supplier_sku_id` 关联 `SupplierSku`，且一个 Supplier SKU 只有一条当前 Offer。
- 历史 `supplier_offers.supplier_sku` 已迁移到 `SupplierSku.supplier_sku_code` 并从最终数据库删除；直接 Offer API 只接受 `supplier_sku_code`。
- 导入工作簿列名 `supplier_sku` 仅作为文件格式兼容边界，导入时映射为 `supplier_sku_code`，不是数据库列或 Offer JSON 字段。
- `price` 继续保存当前价格；对于模式 A，通用集成 API 将其命名为 `cost_price`。
- 本期每个 `SupplierSku` 只保留一条当前 `SupplierOffer`。
- `stock_qty`、`moq`、`lead_time_days` 和库存快照保持现有职责。

模式 A 的成本查询不返回税费、运费、阶梯价或最终采购成本，只返回货号当前成本价和币种。

### 5.5 IntegrationClient

系统调用方使用独立凭证，不使用网页 Session。

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | UUID | 主键 |
| `name` | String(120) | 调用方名称 |
| `token_prefix` | String(24) | 定位凭证，不能用于认证 |
| `token_hash` | String(255) | 仅保存令牌哈希 |
| `scopes` | JSON array | 权限范围 |
| `expires_at` | timestamp nullable | 到期时间 |
| `is_active` | boolean | 是否启用 |
| `last_used_at` | timestamp nullable | 最近使用时间 |

权限范围：

- `suppliers:read`
- `supplier-brands:read`
- `supplier-skus:read`
- `supplier-costs:read`

## 6. 调用方映射模型

Supplier Network 不保存 `client_sku_id`。各调用方在自己的数据库中保存映射。

调用方供应商主数据建议增加：

- `supplier_network_supplier_id`
- `supplier_network_supplier_code`
- `supplier_network_bound_at`

调用方的 SKU—供应商关系建议增加：

- `supplier_network_sku_id`
- `supplier_network_supplier_sku`
- `supplier_network_match_status`
- `supplier_network_match_score`
- `supplier_network_match_reasons`
- `supplier_network_confirmed_by`
- `supplier_network_confirmed_at`

一个调用方 SKU 可以关联多个供应商。每一条调用方 SKU—供应商关系分别确认一个 `supplier_network_sku_id`。

## 7. 自动匹配与人工确认

匹配在调用方执行，因为调用方拥有本地 SKU 主数据和最终映射关系。Supplier Network 通过 SKU 列表接口提供匹配所需的标准字段。

建议匹配优先级：

1. 条码完全一致；
2. 品牌与原厂型号完全一致；
3. 品牌与供应商货号完全一致；
4. 品牌、型号和关键规格一致；
5. 商品名称和属性相似度。

规则：

- 自动流程只能生成 `PROPOSED` 候选。
- 无论匹配分数多高，都必须由业务人员确认后才能写入 `CONFIRMED`。
- 人工拒绝的候选保存为 `REJECTED`，避免重复推荐。
- 成本变化不触发重新匹配。
- 仅当供应商、品牌合作关系或 Supplier SKU 失效时，调用方才将现有映射标记为不可用并要求重新处理。

## 8. 通用集成 API

接口前缀：

```text
/api/integrations/v1
```

基础接口：

```http
GET  /api/integrations/v1/suppliers
GET  /api/integrations/v1/suppliers/{supplier_id}
GET  /api/integrations/v1/suppliers/{supplier_id}/brands
GET  /api/integrations/v1/suppliers/{supplier_id}/skus
GET  /api/integrations/v1/suppliers/{supplier_id}/skus/{supplier_sku_id}/cost
POST /api/integrations/v1/sku-costs/query
```

供应商、品牌合作和 Supplier SKU 列表都支持 `updated_since`、不透明 `cursor`、`include_inactive` 和 `limit`。默认 `limit=100`，范围 1..500。`include_inactive=true` 时，缺少当前合作关系的孤儿 Supplier SKU 以 `status=INACTIVE`、`commercial_mode=null` 返回；正常有效行的模式仍只能是三种正式模式之一。

### 8.1 批量成本查询

`client_sku_id` 是调用方自己的关联标识。Supplier Network 不保存、不解释该字段，只在响应中原样返回。

请求：

```json
{
  "items": [
    {
      "client_sku_id": "调用方自己的SKU ID",
      "supplier_id": "supplier-uuid",
      "supplier_sku_id": "supplier-sku-uuid"
    }
  ]
}
```

成功行：

```json
{
  "client_sku_id": "调用方自己的SKU ID",
  "supplier_id": "supplier-uuid",
  "supplier_sku_id": "supplier-sku-uuid",
  "supplier_sku_code": "A-001",
  "cost_price": "28.5000",
  "currency": "CNY",
  "cost_updated_at": "2026-09-08T10:00:00Z",
  "status": "OK"
}
```

错误行：

```json
{
  "client_sku_id": "调用方自己的SKU ID",
  "supplier_id": "supplier-uuid",
  "supplier_sku_id": "supplier-sku-uuid",
  "status": "ERROR",
  "error_code": "NOT_SELF_PURCHASE",
  "message": "该货号所属品牌不是自营采购模式"
}
```

批量请求接受 1..500 行，通过 HTTP 200 按输入顺序返回逐行结果。批量 JSON 或请求结构整体无效时返回 HTTP 400；三个列表的无效不透明游标也返回 HTTP 400 和 `INVALID_CURSOR`。普通列表/路径/查询参数的 FastAPI 框架校验失败返回 HTTP 422。认证、权限、限流和服务异常使用对应 HTTP 状态码；HTTP 401 声明并返回 `WWW-Authenticate: Bearer`。

业务错误码：

- `SUPPLIER_NOT_FOUND`
- `SUPPLIER_INACTIVE`
- `SKU_NOT_FOUND`
- `SKU_INACTIVE`
- `SKU_SUPPLIER_MISMATCH`
- `BRAND_COOPERATION_INACTIVE`
- `NOT_SELF_PURCHASE`
- `COST_PRICE_MISSING`

## 9. 成本查询规则

输入是 `supplier_id + supplier_sku_id`，输出是该货号当前成本价。

依次验证：

1. 供应商组织存在且类型为 `SUPPLIER`；
2. 供应商组织已启用，且 `SupplierProfile` 存在并处于 `APPROVED`；缺失档案或任何非 `APPROVED` 状态都返回 `SUPPLIER_INACTIVE`；
3. Supplier SKU 存在且属于该供应商；
4. Supplier SKU 处于启用状态；
5. 根据 Supplier SKU 的 `brand_id` 找到当前有效的品牌合作关系；
6. 合作模式为 `SELF_PURCHASE`；
7. 当前 Supplier Offer 处于有效状态且有价格。

成功时只返回：调用方关联标识、供应商 ID、Supplier SKU ID、供应商货号、成本价、币种和成本更新时间。

## 10. 认证、审计与安全

- 使用 `Authorization: Bearer <integration-token>`。
- 令牌仅在创建时展示一次，数据库只保存哈希。
- 每个调用方使用独立令牌和最小权限范围。
- 成本接口必须具有 `supplier-costs:read`。
- 管理端支持创建、到期、轮换和停用；轮换或停用后旧令牌立即失效。
- 调用方可以发送 `X-Request-ID`；成本请求在成功及可识别调用方的 400/403/404/409/429/5xx 结果上各写一条聚合审计事件。
- 审计记录包含调用方 ID、请求 ID、接口、结果数量、错误数量和时间，不记录完整令牌、成本值或 `client_sku_id`。
- 日志不得输出成本批量响应正文。
- 默认限流是每个 Integration Client 每 60 秒 600 次，所有 scope 共享额度；429 返回整数秒 `Retry-After`。
- 当前单 Uvicorn worker 部署使用进程内固定窗口限流器；多 worker 或多实例必须改用共享网关/数据存储限流器。

## 11. 增量同步

第一阶段不实现推送：

- 调用方定时使用 `updated_since` 增量获取供应商和 Supplier SKU。
- 调用方在绑定或重新匹配时拉取指定供应商的品牌和 SKU。
- 调用方在需要使用成本时实时调用成本接口。
- 成本变更不影响已经确认的 SKU 映射。
- 后续如调用量增加，可增加变更 Webhook，但不改变现有资源 ID 和查询接口。

## 12. 已完成的数据迁移

1. 从历史非空 Product 品牌值创建并按规范化名称去重 `Brand`。
2. 为现有供应商与其品牌创建 `SupplierBrandCooperation`，已注册供应商的既有关系初始化为 `SELF_PURCHASE`。
3. 从每条既有 `SupplierOffer` 创建稳定 `SupplierSku`，并保留原 Offer ID、价格、库存、MOQ、交期和库存快照关系。
4. 过渡期 catch-up 迁移再次协调迟到写入，之后把 `products.brand_id` 和 `supplier_offers.supplier_sku_id` 收紧为非空。
5. 最终迁移 `cc83f7e534a1` 删除历史 `products.brand` 和 `supplier_offers.supplier_sku` 列；当前 Alembic head 为 `cc83f7e534a1`。
6. 空品牌、重复身份或缺失外键会在收紧前显式失败，不静默合并或截断；外部调用方映射仍由调用方保存。

迁移链已在全新 PostgreSQL 测试数据库及历史夹具上验证，应用不以运行时自动建表替代 Alembic。真实业务库备份与迁移仍需在部署窗口单独授权执行。

## 13. 界面调整

Supplier 工作台：

- 商品和报价页面显示稳定的 Supplier SKU ID 与供应商货号。
- 模式 A SKU 的现有价格字段在界面中明确显示为“成本价”。
- 供应商可以更新成本价，但不能自行修改平台确认的品牌合作模式。
- 商品和报价 API 按最多 500 行分块拉取完整结果，浏览器表格每页渲染 50 行；筛选、编辑和 Offer 商品选项基于完整客户端列表。
- 导入预览可筛选需修正行，批量排除后仍保留原行并允许一键恢复；只有 `included` 行参与重复校验和最终导入。

平台管理端：

- 管理供应商与品牌的正式合作关系。
- 同一供应商与品牌不能同时启用两种模式。
- 可以查看 Supplier SKU 状态和成本变更审计。
- 管理集成调用方、权限范围和令牌轮换。

## 14. 验收标准

- 一个供应商可以分别以模式 A、模式 B 关联不同品牌。
- 同一供应商和品牌不能同时存在两种有效模式。
- `SupplierSku.id` 在成本更新后保持不变。
- 模式 A SKU 可以返回当前成本价。
- 模式 B、模式 C SKU 返回 `NOT_SELF_PURCHASE`。
- 传入其他供应商的 SKU 返回 `SKU_SUPPLIER_MISMATCH`。
- 停用供应商、合作关系或 SKU 后，成本接口返回相应错误。
- 批量查询单行失败不影响其他行。
- 不同 Integration Client 的凭证、权限和审计记录相互隔离。
- 调用方保存确认映射后，成本变化不要求重新匹配。
