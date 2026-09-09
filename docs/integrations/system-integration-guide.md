# Supplier Network 通用系统接入指南

状态：已实现并通过自动化契约验证
版本：v1
日期：2026-09-09

## 1. 文档目的

本文面向外部系统开发与业务实施人员，说明调用方如何：

1. 绑定 Supplier Network 供应商；
2. 获取该供应商的品牌和 Supplier SKU；
3. 自动生成调用方 SKU 与 Supplier SKU 的匹配候选；
4. 由业务人员确认匹配；
5. 保存稳定的 `supplier_network_sku_id`；
6. 获取模式 A（自营采购）SKU 的当前成本价。

Supplier Network 提供与具体业务系统无关的通用集成 API。不同调用方使用独立凭证调用同一套接口。

## 2. 接入边界

Supplier Network 负责：

- 供应商稳定标识；
- 品牌及品牌合作模式；
- Supplier SKU 稳定标识和匹配字段；
- 模式 A SKU 的当前成本价。

调用方负责：

- 调用方自己的供应商和 SKU 主数据；
- 调用方 SKU 与供应商的业务关系；
- 调用方 SKU 与 Supplier SKU 的自动候选匹配和人工确认；
- 保存确认后的 Supplier Network 外部 ID；
- 采购及调用方内部的其他业务处理。

Supplier Network 不保存 `client_sku_id`，也不替调用方确认 SKU 映射。

## 3. 环境与基础地址

本地联调地址：

```text
http://127.0.0.1:6790/api/integrations/v1
```

正式环境基础地址由部署配置提供。调用方不应在代码中硬编码域名，应通过环境配置保存 `SUPPLIER_NETWORK_BASE_URL`。

## 4. 认证

调用方使用独立的只读 Integration Client 令牌：

```http
Authorization: Bearer <integration-token>
Accept: application/json
```

建议权限：

```text
suppliers:read
supplier-brands:read
supplier-skus:read
supplier-costs:read
```

要求：

- 调用方不得使用供应商或平台管理员的网页 Session。
- 令牌必须存入密钥管理或受控环境变量，不得写入代码或日志。
- 测试和正式环境使用不同令牌。
- 收到 HTTP 401（响应包含 `WWW-Authenticate: Bearer`）时停止业务重试并检查令牌；收到 HTTP 403 时检查权限范围。
- 为凭证设置最小 scope 和合理到期时间；轮换后旧令牌立即失效，停用后该令牌立即返回 401。
- 不要把 `token_prefix` 当作凭证；令牌遗失时必须轮换，不能从平台取回明文。

### 4.1 平台 API 凭证与供应商 API 凭证

平台支持两类只读 Integration Client：

- `SYSTEM`：平台管理员在 `/admin#integrations` 的“平台 API 凭证”创建，适用于平台级同步，可读取平台范围内的数据。
- `SUPPLIER`：供应商在 `/app#erp-integration` 创建；凭证的所有者由当前供应商组织确定，不能指定其他组织。

供应商凭证为只读凭证，仅能访问自己的供应商组织。访问其他供应商 ID 返回 HTTP 404。平台凭证与供应商凭证都使用相同的 `Authorization: Bearer <integration-token>` 请求头。

创建或轮换后，完整令牌只展示一次，数据库仅保存令牌哈希和可检索前缀。合作绑定 UUID 只是合作标识，不是凭证。它不参与 Bearer 鉴权，也不扩大数据权限。运营商没有 ERP API 凭证流程。

## 5. 标识说明

| 字段 | 来源 | 是否稳定 | 调用方用途 |
|---|---|---|---|
| `supplier_id` | Supplier Network | 是 | 绑定调用方供应商 |
| `supplier_code` | Supplier Network | 是 | 搜索和人工识别 |
| `supplier_sku_id` | Supplier Network | 是 | 绑定调用方 SKU—供应商关系 |
| `supplier_sku_code` | 供应商 | 原则上稳定 | 页面展示、辅助匹配 |
| `client_sku_id` | 调用方 | 是 | 传递并关联调用方自己的 SKU ID |

调用方不能用公司名称、邮箱、品牌名称或 `supplier_sku_code` 代替 Supplier Network UUID 作为最终关联主键。

## 6. 调用方数据模型建议

### 6.1 调用方供应商主数据

建议增加：

| 字段 | 说明 |
|---|---|
| `supplier_network_supplier_id` | Supplier Network 的 `supplier_id` |
| `supplier_network_supplier_code` | 便于搜索和核对的供应商编码 |
| `supplier_network_bound_at` | 绑定时间 |
| `supplier_network_sync_status` | `ACTIVE` / `INACTIVE` / `ERROR` |

`supplier_network_supplier_id` 在调用方供应商主数据中应唯一，防止同一个 Supplier Network 供应商被重复绑定。

### 6.2 调用方 SKU—供应商关系

建议增加：

| 字段 | 说明 |
|---|---|
| `supplier_network_sku_id` | 确认后的 Supplier SKU UUID |
| `supplier_network_supplier_sku` | 供应商货号快照，用于展示 |
| `supplier_network_match_status` | `UNMATCHED` / `PROPOSED` / `CONFIRMED` / `REJECTED` / `INVALID` |
| `supplier_network_match_score` | 自动匹配评分 |
| `supplier_network_match_reasons` | JSON，记录命中的字段和理由 |
| `supplier_network_confirmed_by` | 调用方确认人 |
| `supplier_network_confirmed_at` | 调用方确认时间 |
| `supplier_network_last_checked_at` | 最近检查 Supplier SKU 状态时间 |

唯一性建议：同一条调用方 SKU—供应商关系最多绑定一个 `supplier_network_sku_id`。

## 7. 完整接入流程

### 7.1 绑定供应商

1. 调用方调用供应商列表接口。
2. 用户通过供应商编码、名称等信息选择 Supplier Network 供应商。
3. 调用方保存 `supplier_id` 和 `supplier_code`。
4. 调用方调用供应商详情接口再次校验状态。

### 7.2 拉取品牌和 Supplier SKU

1. 调用方获取供应商的品牌合作关系。
2. 调用方获取供应商的 Supplier SKU 列表。
3. 调用方保存必要的本地同步缓存，供匹配页面使用。
4. 对于成本接入，只处理 `commercial_mode=SELF_PURCHASE` 的品牌和 SKU。

### 7.3 自动匹配

建议匹配顺序：

1. 条码完全一致；
2. 品牌与原厂型号完全一致；
3. 品牌与供应商货号完全一致；
4. 品牌、型号和关键规格一致；
5. 商品名称和属性相似。

每个候选应显示：

- 调用方 SKU 编码和名称；
- Supplier SKU 编码和名称；
- 品牌、型号、条码、原厂料号；
- 匹配分数；
- 匹配原因；
- 冲突或缺失字段。

自动匹配只能生成 `PROPOSED`，不能直接写入 `CONFIRMED`。

### 7.4 人工确认

业务人员确认后，调用方将 `supplier_sku_id` 写入对应的调用方 SKU—供应商关系，并保存确认人和确认时间。

成本变化不会改变 `supplier_sku_id`，因此不需要重新匹配。仅在 Supplier SKU 或品牌合作关系失效时，将映射标为 `INVALID` 并要求处理。

### 7.5 获取成本

调用方使用已经确认的：

```text
supplier_network_supplier_id + supplier_network_sku_id
```

调用成本接口。Supplier Network 先验证供应商组织存在且类型正确，再确认组织已启用、`SupplierProfile` 存在且状态为 `APPROVED`，之后验证 SKU 归属及模式 A 状态并返回当前成本价。组织停用、缺少档案或档案不是 `APPROVED` 均视为 `SUPPLIER_INACTIVE`，不能读取成本。

## 8. API 说明

以下路径均相对于 `/api/integrations/v1`。

所有集成接口均为只读接口。平台没有提供供外部 ERP 写入业务数据的 Integration API。

三个列表接口（供应商、品牌合作、Supplier SKU）采用相同的同步参数：

| 参数 | 默认值/范围 | 说明 |
|---|---|---|
| `updated_since` | 可选，带时区时间 | 只返回有效更新时间严格晚于该水位的资源；晚于服务端当前水位时返回 400，不允许把检查点向未来推进 |
| `cursor` | 可选，不透明字符串 | 传入上一页 `next_cursor`；游标绑定资源、供应商、`updated_since`、`include_inactive` 和本轮服务端快照，不得解析、修改或跨查询条件复用 |
| `limit` | 默认 100，范围 1..500 | 单页条数 |
| `include_inactive` | 默认 `false` | 为 `true` 时同时返回 `INACTIVE` 资源，供失效映射对账 |

每页（包括空页和最后一页）都返回相同的 `sync_watermark`，它是本轮固定的服务端快照上界。首请求通过数据库 writer fence 等待此前已开始的资源写事务完成；此后开始的写事务会取得严格晚于该水位的数据库时间，因此不会出现“写入时间早于水位、提交却晚于水位”的缺口。首请求可能因此短暂等待正在提交的目录写事务。

必须拉到 `next_cursor=null` 才算完成一轮同步；同一轮翻页期间保持 `updated_since` 和 `include_inactive` 不变，并在完成后把响应的 `sync_watermark` 持久化为下一轮 `updated_since`。翻页期间发生的新增或更新不会混入当前轮，而会在下一轮返回。

### 8.1 获取供应商列表

```http
GET /suppliers?updated_since=2026-09-08T00:00:00Z&limit=100
```

响应示例：

```json
{
  "items": [
    {
      "supplier_id": "5d5a523d-4272-4a99-80a3-37797a90d094",
      "supplier_code": "SUP-E65BA4",
      "supplier_name": "北京沐光盛汇商贸有限公司",
      "status": "ACTIVE",
      "updated_at": "2026-09-08T10:00:00Z"
    }
  ],
  "next_cursor": null,
  "sync_watermark": "2026-09-08T10:05:00Z"
}
```

### 8.2 获取供应商详情

```http
GET /suppliers/{supplier_id}
```

用于绑定时校验供应商身份与状态。

### 8.3 获取品牌合作关系

```http
GET /suppliers/{supplier_id}/brands
```

响应示例：

```json
{
  "items": [
    {
      "brand_id": "brand-uuid",
      "brand_code": "BRAND-A",
      "brand_name": "品牌A",
      "commercial_mode": "SELF_PURCHASE",
      "status": "ACTIVE",
      "updated_at": "2026-09-08T10:00:00Z"
    }
  ],
  "next_cursor": null,
  "sync_watermark": "2026-09-08T10:05:00Z"
}
```

合作模式：

| 值 | 含义 | 可调用成本接口 |
|---|---|---|
| `SELF_PURCHASE` | 模式 A，自营采购 | 是 |
| `JOINT_OPERATION` | 模式 B，联营 | 否 |
| `B2B` | 模式 C，ToB 采购或外贸合作 | 否 |

### 8.4 获取 Supplier SKU

```http
GET /suppliers/{supplier_id}/skus?updated_since=2026-09-08T00:00:00Z&limit=200
```

响应示例：

```json
{
  "items": [
    {
      "supplier_sku_id": "supplier-sku-uuid",
      "supplier_sku_code": "A-001",
      "brand_id": "brand-uuid",
      "brand_name": "品牌A",
      "product_name": "商品名称",
      "model": "M100",
      "manufacturer_part_number": "MPN-100",
      "barcode": "6900000000001",
      "commercial_mode": "SELF_PURCHASE",
      "status": "ACTIVE",
      "updated_at": "2026-09-08T10:00:00Z"
    }
  ],
  "next_cursor": null,
  "sync_watermark": "2026-09-08T10:05:00Z"
}
```

调用方使用这些字段生成本地匹配候选。调用方不应根据一次模糊匹配直接确认关系。

默认列表只返回有效供应商、有效 SKU、有效品牌及有效合作关系的交集。`include_inactive=true` 会返回停用资源；如果 Supplier SKU 结构上缺少当前品牌合作关系，它仍以 `status=INACTIVE` 返回，且 `commercial_mode=null`。调用方必须允许该字段在这种失效/孤儿记录上为空，不能虚构合作模式。

### 8.5 获取单个 SKU 成本

```http
GET /suppliers/{supplier_id}/skus/{supplier_sku_id}/cost
```

响应示例：

```json
{
  "supplier_id": "supplier-uuid",
  "supplier_sku_id": "supplier-sku-uuid",
  "supplier_sku_code": "A-001",
  "cost_price": "28.5000",
  "currency": "CNY",
  "cost_updated_at": "2026-09-08T10:00:00Z"
}
```

### 8.6 批量获取 SKU 成本

```http
POST /sku-costs/query
Content-Type: application/json
```

调用方通过 `client_sku_id` 传递自己的 SKU ID：

`items` 必须包含 1..500 行。超过 500 行应由调用方拆批；空数组、超限或结构错误返回 HTTP 400，不进入逐行业务处理。

```json
{
  "items": [
    {
      "client_sku_id": "CLIENT-SKU-1001",
      "supplier_id": "supplier-uuid",
      "supplier_sku_id": "supplier-sku-uuid"
    },
    {
      "client_sku_id": "CLIENT-SKU-1002",
      "supplier_id": "supplier-uuid",
      "supplier_sku_id": "another-supplier-sku-uuid"
    }
  ]
}
```

成功响应：

```json
{
  "items": [
    {
      "client_sku_id": "CLIENT-SKU-1001",
      "supplier_id": "supplier-uuid",
      "supplier_sku_id": "supplier-sku-uuid",
      "supplier_sku_code": "A-001",
      "cost_price": "28.5000",
      "currency": "CNY",
      "cost_updated_at": "2026-09-08T10:00:00Z",
      "status": "OK"
    }
  ]
}
```

单行错误示例：

```json
{
  "client_sku_id": "CLIENT-SKU-1002",
  "supplier_id": "supplier-uuid",
  "supplier_sku_id": "another-supplier-sku-uuid",
  "status": "ERROR",
  "error_code": "NOT_SELF_PURCHASE",
  "message": "该货号所属品牌不是自营采购模式"
}
```

批量接口按输入顺序返回结果。单行错误不会使其他行失败；逐行业务错误随 HTTP 200 返回。单个成本接口则以 HTTP 404 表示供应商/SKU 不存在，以 HTTP 409 表示停用、归属不符、非模式 A、合作失效或缺少成本。

## 9. HTTP 状态和错误码

| HTTP 状态 | 含义 | 调用方处理 |
|---|---|---|
| 200 | 成功；批量响应可能包含单行错误 | 逐行处理 |
| 400 | 三个列表的 `cursor` 无效（`INVALID_CURSOR`）、`updated_since` 晚于服务端当前水位（`FUTURE_SYNC_WATERMARK`），或批量成本请求 JSON/整体结构无效 | 修正游标、水位或批量请求，不自动重试 |
| 401 | 令牌无效或过期 | 停止重试并告警 |
| 403 | 权限不足 | 检查 Integration Client scope |
| 404 | 单资源不存在 | 将本地绑定标为待检查 |
| 409 | 单个成本查询的资源状态、归属、合作模式或成本条件不满足 | 按业务错误码修正绑定或停止使用成本 |
| 422 | 三个列表接口的受约束查询参数未通过框架校验，例如 `limit` 越界或 `updated_since` 格式错误 | 修正列表参数，不自动重试 |
| 429 | 调用频率过高 | 按 `Retry-After` 重试 |
| 500/502/503/504 | 服务异常 | 指数退避重试 |

业务错误码：

| 错误码 | 含义 | 调用方建议处理 |
|---|---|---|
| `SUPPLIER_NOT_FOUND` | 供应商不存在 | 解除或重新选择供应商 |
| `SUPPLIER_INACTIVE` | 供应商组织停用、缺少供应商档案或档案未审核通过 | 禁止继续使用并提示业务人员 |
| `SKU_NOT_FOUND` | Supplier SKU 不存在 | 将映射标为 `INVALID` |
| `SKU_INACTIVE` | Supplier SKU 已停用 | 将映射标为 `INVALID` |
| `SKU_SUPPLIER_MISMATCH` | SKU 不属于传入供应商 | 修正本地绑定 |
| `BRAND_COOPERATION_INACTIVE` | 品牌合作关系失效 | 停止成本同步并提示业务人员 |
| `NOT_SELF_PURCHASE` | 不是模式 A | 不读取成本 |
| `COST_PRICE_MISSING` | 当前没有成本价 | 标记成本缺失，不使用旧值静默下单 |

## 10. 同步建议

### 10.1 供应商和 SKU

- 每日或按业务需要调用 `updated_since` 增量同步。
- 绑定供应商和进入匹配页面时立即刷新一次。
- 使用 `next_cursor` 完成全部分页后，再把服务端返回的 `sync_watermark` 提交为下一轮 `updated_since`。
- 如果同步中途失败，不更新水位，使用原水位重试。

### 10.2 成本

- 调用方在需要使用模式 A 成本时调用单个或批量成本接口。
- 成本变化不触发 SKU 重新匹配。
- 如果调用方缓存成本，必须同时保存 `cost_updated_at` 并明确缓存更新时间。
- `COST_PRICE_MISSING`、失效或模式错误不能静默回退到另一个供应商的成本。

## 11. 重试、关联与审计

- 每次请求发送唯一 `X-Request-ID`；重试时沿用原请求 ID，并在调用方本地记录重试次数。
- GET 和成本查询 POST 均为只读操作，可以安全重试。
- 默认每个 Integration Client 在一个 60 秒固定窗口内最多 600 次已认证请求，所有 scope 共用额度；超限返回 429，并以整数秒 `Retry-After` 指示当前窗口剩余时间。
- 5xx 使用指数退避并限制最大重试次数。
- 调用方日志可以记录 `client_sku_id`、`supplier_id`、`supplier_sku_id`、HTTP 状态和错误码，但不得记录认证令牌。
- 当前受支持部署使用单个 Uvicorn worker，因此限流器是进程内状态。多 worker 或多实例部署必须先接入网关或共享数据存储限流器，否则每个进程会分别计算 600/60 配额。
- 每个可识别 Integration Client 的成本请求写入一条聚合审计事件，包括调用方 ID、请求 ID、路径、成功数和错误数；400、403、404、409、429 及认证后的 5xx 也会审计。事件不保存令牌、成本值或 `client_sku_id`；无法认证的 401 不伪造 Actor。

## 12. 联调验收用例

1. 调用方能获取并绑定指定 Supplier Network 供应商。
2. 调用方能获取该供应商不同品牌及各自合作模式。
3. 调用方能获取 Supplier SKU 的条码、型号、供应商货号等匹配字段。
4. 自动匹配只生成候选，未经人工确认不写入最终映射。
5. 人工确认后正确保存 `supplier_network_sku_id`。
6. 模式 A SKU 返回当前成本价。
7. 模式 B、模式 C SKU 返回 `NOT_SELF_PURCHASE`。
8. 传入不属于该供应商的 SKU 返回 `SKU_SUPPLIER_MISMATCH`。
9. 成本修改后映射 ID 不变，调用方能获取新成本。
10. 一个批量请求中的错误行不影响成功行。
11. 无效令牌、缺少 scope、限流和服务异常能按规范处理。
12. Supplier SKU 停用后，调用方将本地映射标记为 `INVALID`。

## 13. 调用方上线检查清单

- [ ] 已配置环境化的 Supplier Network 基础地址。
- [ ] 已安全配置 Integration Client 令牌。
- [ ] 调用方供应商主数据已支持保存 `supplier_network_supplier_id`。
- [ ] 调用方 SKU—供应商关系已支持保存 `supplier_network_sku_id`。
- [ ] 已实现自动候选匹配和人工确认界面。
- [ ] 未确认映射不能调用或采用 Supplier 成本。
- [ ] 已实现供应商、品牌和 SKU 的增量同步。
- [ ] 已实现单个或批量成本查询。
- [ ] 已处理逐行业务错误、HTTP 错误和重试。
- [ ] 日志中不包含令牌。
- [ ] 已完成全部联调验收用例。
