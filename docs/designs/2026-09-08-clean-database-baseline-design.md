# PostgreSQL 全新基线与数据重建设计

状态：已确认
日期：2026-09-08

## 1. 目标

- 放弃兼容当前业务库和测试库中的全部历史业务数据及旧 Alembic 版本。
- 将现有两条迁移压缩为一份能够独立创建当前完整结构的基线迁移。
- 正式运行和自动化测试继续只使用 PostgreSQL 16，数据库服务端口统一为 `6432`。
- 保持 `./start.sh` 为默认启动入口，`./start.sh test` 使用独立、持久化的测试数据库。
- 为后续供应商、品牌、合作模式和 SKU 映射功能保留可靠的增量迁移能力。

## 2. 采用方案

继续使用 Alembic，但重置迁移历史：

- 删除 revision `4d4ef4adb60c` 和 `7f22c89a41bd` 的迁移脚本。
- 新建唯一 revision `20260908_baseline`，并设置 `down_revision = None`。
- 新基线直接创建当前 SQLAlchemy 模型对应的完整表、索引、唯一约束和外键。
- 新基线不包含旧供应商角色的数据转换；全新数据只允许当前角色模型。
- `alembic.ini`、`migrations/env.py` 和启动前的 `alembic upgrade head` 保留。
- 后续迁移统一以 `20260908_baseline` 为起点。

不采用启动时 `Base.metadata.create_all()`，因为它不能可靠修改已有列、约束和索引；不采用独立 SQL 初始化脚本，避免数据库结构在 ORM 模型和 SQL 文件中重复维护。

## 3. 数据清理边界

经确认，以下历史数据全部删除且不制作 SQL 备份：

- 业务 Compose 项目的 PostgreSQL 命名卷 `supplier_postgres` 中的全部数据。
- 测试 Compose 项目 `supplier-tests` 的 PostgreSQL 命名卷 `supplier_test_postgres` 中的全部数据。
- 两个数据库中的供应商、用户、商品、SKU、报价、库存、申请、文档、导入任务、事件日志及 `alembic_version`。

清理前必须通过 Compose project、volume 声明和 Docker label 解析实际卷名；只允许删除这两个精确匹配且经核验的命名卷，不使用通配符，不清理其他 Docker 数据。

以下内容不得删除或输出：

- `.env` 及其中的凭证。
- PostgreSQL 连接配置、应用配置和源代码。
- 非上述两个目标卷的容器、网络或数据卷。

迁移文件可以从 Git 历史恢复；未制作备份的 PostgreSQL 数据卷删除后不可恢复。

## 4. 重建流程

1. 停止业务应用及两套 PostgreSQL 服务，确保没有写入。
2. 解析并核验业务卷、测试卷的精确名称和 Compose 标签。
3. 删除且只删除核验通过的两个 PostgreSQL 命名卷。
4. 以新卷重新创建业务数据库，由 `./start.sh` 自动执行 `alembic upgrade head`。
5. 运行 `./start.sh test`，由同一基线初始化新的持久化测试数据库。
6. 业务库仅执行当前安全 bootstrap；不恢复历史供应商、商品或报价数据。
7. 测试库在首次初始化后继续跨 `./start.sh test` 运行持久化，不在测试结束时销毁。

## 5. 启动密码安全

持久化数据库的密码不能通过修改 `.env` 自动同步。启动逻辑必须区分：

- **不存在业务数据卷：** 允许从模板创建 `.env` 并生成新的 PostgreSQL 密码，然后创建数据库。
- **已存在业务数据卷：** 如果 `.env` 缺失，或者 `POSTGRES_PASSWORD` 为空、占位或待生成，启动立即终止并给出恢复说明；不得生成新密码后尝试连接旧数据库。

这项保护只针对业务数据库。测试数据库使用测试 Compose 中固定、隔离的测试凭证。

## 6. 自动化测试

- 先增加会失败的基线契约测试，要求仓库只有一个 revision，revision 为 `20260908_baseline` 且 `down_revision = None`。
- 在全新的临时 PostgreSQL 数据库执行 `alembic upgrade head`，验证当前完整表集合、关键索引、外键及 `alembic_version`。
- 删除依赖旧 revision 和旧角色转换路径的迁移测试，保留对当前角色模型的行为测试。
- 增加启动密码保护测试：已有卷且密码配置不可用时必须拒绝启动；新卷才允许生成密码。
- 连续运行两次 `./start.sh test`，确认测试均通过且测试卷身份保持不变。

## 7. 验收标准

- `migrations/versions/` 中只有一份有效迁移脚本。
- 业务库和测试库的 `alembic_version.version_num` 都是 `20260908_baseline`。
- 业务库不存在旧供应商、旧用户、旧商品、旧报价和旧库存数据。
- PostgreSQL 在两套环境中均监听容器内部端口 `6432`。
- `./start.sh` 启动成功，`/api/health` 返回成功。
- `./start.sh test` 连续执行两次全部通过，第二次复用同一测试卷。
- README、验证文档及供应商/品牌/SKU 接入计划不再引用旧 revision。
- `.env` 未进入 Git，且验证输出不包含其中的值。

## 8. 回退边界

代码变更可通过 Git 回退，但数据库数据不回退。若基线初始化失败，只能修正基线后再次删除本次新建的空白目标卷并重建；不得把旧 revision 标记到结构不匹配的数据库上。
