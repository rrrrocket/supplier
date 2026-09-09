# 运营商入驻、供应商市场与 ERP 绑定设计

## 目标

在现有平台管理员与供应商之外增加运营商身份。运营商申请并经平台审核后，可浏览已审核启用的供应商、查看联系方式、发起合作；供应商确认合作后，系统生成稳定的 ERP 绑定关系，并将业务接口访问限制在有效合作范围内。

## 已确认范围

- 新增 `OPERATOR` 组织类型与用户角色，运营商与供应商、平台管理员隔离。
- 运营商通过公开页面申请入驻，平台管理员审核通过后创建组织和初始账户。
- 申请资料只有联系人、手机号、邮箱必填；公司名称、信用代码、运营类型、渠道、地区、主营类目、目标市场、ERP 名称、网站、说明和资质均选填。
- 一个运营商组织第一版只有一个主管理员账户。
- 供应商市场只展示组织启用且资料状态为 `APPROVED` 的供应商。
- 未登录访客看到脱敏联系方式，审核通过的运营商及平台管理员看到完整联系方式；查看完整联系方式记审计事件。
- 一个供应商可属于多个类目，列表不重复；支持关键词、类目、地区、供应商类型、合作模式和能力筛选。
- 运营商发起合作，供应商接受或拒绝，平台不做第二次审批。
- 同一运营商与供应商最多一个有效合作；拒绝后可重新申请，双方可终止，历史保留。
- 合作确认后生成 ERP 绑定记录；稳定 UUID 与名称修改解耦。
- 运营商可创建、轮换、停用自己的集成凭证；明文只展示一次，数据库只保存摘要。
- 目录基础信息可公开查询；品牌、SKU、报价等业务数据仅允许访问有效合作供应商，合作终止后立即失效。
- 第一版提供站内待处理提醒，不做聊天、合同、签章、交易结算、评分、智能推荐或自动 SKU 映射。

## 方案比较

### 方案 A：复用供应商申请和工作台

在现有表中增加身份字段并让运营商复用供应商页面。改动少，但会让供应商资料、合作申请和 ERP 权限混在一起，后续条件分支会持续增长，拒绝采用。

### 方案 B：独立运营商域，共享认证与基础组织模型（采用）

保留统一的组织、用户、会话与审计基础设施；新增运营商申请/资料、运营商—供应商合作、ERP 绑定三组实体，新增独立 `/operator` 工作台与对应 API。边界清晰，现有供应商和系统级集成客户端保持兼容。

### 方案 C：拆分独立运营商服务

独立部署可获得最强隔离，但当前体量会引入跨服务认证、事务与部署成本，不适合第一版。

## 身份和权限

`OrganizationType` 增加 `OPERATOR`，`UserRole` 增加 `OPERATOR`。合法组合只有：

| 组织类型 | 用户角色 | 工作台 |
| --- | --- | --- |
| `PLATFORM` | `PLATFORM_ADMIN` | `/admin` |
| `SUPPLIER` | `SUPPLIER` | `/app` |
| `OPERATOR` | `OPERATOR` | `/operator` |

后端增加 `OperatorUser` 依赖，任何角色与组织类型不匹配的会话都返回 403。公共页面认证跳转根据上述组合选择工作台；未知或不匹配身份不视为已登录成员。

## 数据模型

### OperatorApplication

- `application_no`: 唯一申请编号，格式 `OPR-YYYYMMDD-XXXXXX`。
- `contact_name`, `phone`, `email`: 非空，唯一必填业务资料。
- `company_name`, `unified_social_credit_code`, `operator_type`, `province`, `city`, `website`, `erp_name`, `message`: 可空。
- `sales_channels`, `categories`, `target_markets`, `qualification_files`: 非空 JSON 数组，默认空数组。
- 审核字段沿用供应商申请语义：`status`, `review_notes`, `approved_organization_id`, `reviewed_by_user_id`, `reviewed_at`。

应用层对邮箱做小写规范化，对电话去除首尾空白；数据库继续依赖 `users.email` 唯一约束防止重复账户。信用代码有值时进行重复申请/组织冲突校验。重复待审核邮箱返回 409；被驳回后可重新提交。

### OperatorProfile

与运营商组织一对一，保存申请中的企业/渠道资料。`display_name` 的显示优先级为公司名称、联系人姓名、运营商组织编码。资料可在工作台更新，但联系人、手机号、邮箱不可更新为空。

### OperatorSupplierCooperation

- `operator_id`, `supplier_id`: 分别指向对应类型组织。
- `status`: `PENDING`, `ACTIVE`, `REJECTED`, `TERMINATED`。
- `categories`, `brands`, `sales_channels`, `target_markets`: JSON 数组。
- `message`, `response_notes`, `requested_by_user_id`, `responded_by_user_id`, `responded_at`, `terminated_by_user_id`, `terminated_at`。
- PostgreSQL 部分唯一索引保证同一双方在 `PENDING` 或 `ACTIVE` 状态下最多一条记录。

状态转换只有：`PENDING -> ACTIVE|REJECTED|TERMINATED`、`ACTIVE -> TERMINATED`。运营商可撤回待确认申请或终止有效合作；供应商可接受、拒绝或终止；管理员只读审计并可执行紧急停用组织/凭证，不代替供应商接受合作。

### ErpBinding

合作进入 `ACTIVE` 时事务内创建，字段为 `cooperation_id`, `operator_id`, `supplier_id`, `status`, `bound_at`, `unbound_at`。一个合作只有一个绑定；合作终止时绑定改为 `INACTIVE`，不删除 UUID。

### IntegrationClient 扩展

- `client_type`: `SYSTEM` 或 `OPERATOR`，现有数据迁移为 `SYSTEM`。
- `owner_organization_id`: 系统客户端为空，运营商客户端必须指向运营商组织。
- 运营商凭证只允许平台定义的四个只读 scope；创建与轮换均复用现有安全 token 生成、摘要保存与一次性展示规则。

## 供应商市场

公开 API 返回供应商基础资料和脱敏联系方式；登录运营商请求同一路由时返回完整联系方式并记录 `SUPPLIER_CONTACT_VIEWED`。为避免列表翻页产生大量审计记录，只有打开供应商详情时记录完整联系方式访问事件，列表始终显示脱敏信息。

目录卡片包含组织 UUID、编码、名称、供应商类型、地区、类目、合作模式、能力标签、商品数量和有效报价数量。详情包含网站及联系方式。过滤使用服务端查询并返回 `{items,total,page,page_size}`；默认每页 50，允许 50/100/200，页面复用统一分页组件。

对于 PostgreSQL JSON 数组筛选使用包含/存在条件；SQLite 单元测试使用等价的 Python 过滤或兼容查询。关键词匹配组织名称、法定名称、地区和类目，大小写不敏感。

## 合作流程

1. 审核通过的运营商在供应商详情提交合作申请。
2. 系统校验供应商仍为审核通过且启用状态，并防止重复待确认/有效申请。
3. 供应商工作台显示待处理数量与申请列表。
4. 供应商接受时，合作与 ERP 绑定在同一事务中转为有效。
5. 双方工作台均显示绑定 UUID、供应商 UUID、运营商 UUID、状态和绑定时间。
6. 任一方终止后，合作、绑定与该供应商的集成数据访问立即失效。

每个状态变化记录审计事件，并让前端刷新站内待处理数字。第一版不新增常驻通知表，待处理数从 `PENDING` 合作实时聚合；成功/失败反馈沿用 toast。

## ERP 访问控制

认证结果增加 `client_type` 和 `owner_organization_id`。系统客户端保持现有行为。运营商客户端规则：

- 供应商列表/详情接口可读取全部公开基础资料，不返回完整联系方式。
- 品牌、SKU 与成本接口必须在查询中连接 `ErpBinding` 和 `OperatorSupplierCooperation`，且二者均为有效状态。
- 请求指定未绑定供应商时返回 404，避免泄露该供应商业务数据是否存在。
- 合作终止、运营商组织停用、凭证停用或过期均立即拒绝受限数据。

凭证在运营商工作台创建，明文响应只出现一次；前端关闭对话框后清除内存与 DOM。轮换使旧 token 立即失效。

## 页面结构

### 公开页面

- 首页新增“寻找供应商”和“运营商入驻”入口。
- `/suppliers`：公开供应商目录。
- `/suppliers/{id}`：公开详情，联系方式脱敏；运营商登录后显示完整联系方式。
- `/operator/apply`：运营商申请页，仅三项必填。

### 运营商工作台 `/operator`

- 概览：供应商总数、待确认申请、合作中供应商、有效 ERP 绑定。
- 寻找供应商：筛选、卡片、详情和申请合作。
- 合作申请：待确认、已拒绝、已终止历史。
- 我的供应商：有效合作及绑定信息。
- ERP 接入：凭证创建、轮换、停用和接入说明。
- 企业资料：运营商资料维护。

### 供应商与管理端

供应商工作台新增“运营商合作”，含待确认、合作中和历史。管理端新增运营商申请、运营商账户和合作审计三个视图；凭证列表标明系统/运营商归属。

## 接口分组

- `POST /api/public/operator-applications`
- `GET /api/public/suppliers`, `GET /api/public/suppliers/{supplier_id}`
- `GET/PATCH /api/operator/profile`
- `GET /api/operator/dashboard`
- `GET/POST /api/operator/cooperations`
- `POST /api/operator/cooperations/{id}/terminate`
- `GET/POST /api/operator/integration-clients`
- `POST /api/operator/integration-clients/{id}/rotate|revoke`
- `GET /api/supplier-operator/cooperations`
- `POST /api/supplier-operator/cooperations/{id}/accept|reject|terminate`
- `GET /api/admin/operator-applications`
- `POST /api/admin/operator-applications/{id}/approve|reject`
- `GET /api/admin/operators`, `GET /api/admin/operator-cooperations`

写接口均基于当前会话进行角色校验；状态变更检查当前状态并以 409 表示冲突。列表采用统一分页响应。

## 迁移与兼容

使用单个 Alembic 迁移增加枚举值对应的字符串数据、四张新表、索引及 `integration_clients` 新字段。因为角色/类型当前是字符串列，无需数据库 Enum 变更。现有集成客户端回填 `client_type='SYSTEM'`，旧 API 合约保持不变。

迁移 downgrade 先移除运营商客户端和新业务表，再删除扩展列；不修改既有供应商、商品、报价数据。部署仍通过 `./start.sh` 自动升级。

## 安全与隐私

- 公开列表和详情使用统一的邮箱/手机脱敏函数，不向前端发送未脱敏值后再隐藏。
- 完整联系方式只从已认证运营商详情接口返回，并记录组织、用户、供应商和时间。
- token 明文不记录日志、不进入审计 payload、不再次查询。
- 所有组织外键由服务端当前身份决定，不接受客户端伪造。
- 运营商业务接口只返回该运营商自己的合作、绑定和凭证。

## 验收标准

- 运营商申请只有联系人、手机号、邮箱为空时返回 422；其他字段为空可成功提交。
- 管理员通过申请后产生运营商组织、资料和可登录账户，临时密码只返回一次。
- 三种合法身份登录后进入各自工作台，身份错配返回 403。
- 目录只出现审核通过且启用的供应商，筛选、分类、脱敏和统一分页正确。
- 运营商能申请合作，供应商能接受/拒绝，重复有效申请被阻止。
- 接受合作原子创建稳定 ERP 绑定；终止后绑定及业务 API 权限即时失效。
- 系统集成客户端行为与当前版本完全兼容。
- 后端、前端、迁移、安全和接口合约测试全部通过，服务重启后健康检查成功。
