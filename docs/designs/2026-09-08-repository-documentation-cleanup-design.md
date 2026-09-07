# 仓库文档归档与无效文件清理设计

状态：已确认
日期：2026-09-08

## 1. 目标

- 根目录仅保留作为代码托管平台入口的 `README.md`。
- 其余 Markdown 文档按用途统一归档到 `docs/`。
- 修复移动产生的全部相对路径与文件清单引用。
- 清除已经被 PostgreSQL、`start.sh` 和当前部署方式替代的旧文件。
- 清除可再生成的本地缓存与虚拟环境，不删除业务数据或本地密钥。
- 使用仓库级 Git 作者 `rrrrocket <standxh@163.com>` 提交已确认改动。

## 2. 文档目录

```text
README.md
docs/
├── README.md
├── architecture/
│   ├── overview.md
│   └── data-dictionary.md
├── product/
│   ├── project-status.md
│   └── roadmap.md
├── operations/
│   └── validation.md
├── integrations/
│   └── system-integration-guide.md
├── designs/
│   ├── 2026-09-08-repository-documentation-cleanup-design.md
│   └── 2026-09-08-supplier-brand-sku-integration-design.md
└── plans/
    └── 2026-09-08-supplier-brand-sku-integration.md
```

根目录 `README.md` 保留为唯一例外，并改为链接到 `docs/README.md` 及各分类文档。

## 3. 文档映射

| 当前路径 | 目标路径 |
|---|---|
| `ARCHITECTURE.md` | `docs/architecture/overview.md` |
| `DATA_DICTIONARY.md` | `docs/architecture/data-dictionary.md` |
| `PROJECT_STATUS.md` | `docs/product/project-status.md` |
| `ROADMAP.md` | `docs/product/roadmap.md` |
| `VALIDATION.md` | `docs/operations/validation.md` |
| `docs/SYSTEM_INTEGRATION_GUIDE.md` | `docs/integrations/system-integration-guide.md` |
| `docs/superpowers/specs/2026-09-08-supplier-brand-sku-integration-design.md` | `docs/designs/2026-09-08-supplier-brand-sku-integration-design.md` |
| `docs/superpowers/plans/2026-09-08-supplier-brand-sku-integration.md` | `docs/plans/2026-09-08-supplier-brand-sku-integration.md` |

所有文档中的特定调用系统名称统一改为“调用方”或“外部业务系统”。接口路径和字段继续使用通用命名。

## 4. 删除范围

### 4.1 已被当前架构替代的跟踪文件

- `app/db/seed.py`：旧演示数据初始化，已由安全的 PostgreSQL bootstrap 取代。
- `data/.gitkeep`：仅为旧本地文件数据库目录占位。
- `deploy/supplier.service`：端口和虚拟环境启动方式与当前 `start.sh`/Compose 架构冲突。
- `scripts/reset_demo.py`：只支持删除旧本地数据库文件。
- `start-macos.command`：旧端口和本地虚拟环境启动器，已由 `start.sh` 取代。
- `scripts/dev.sh`：仅转发到 `start.sh`，没有独立职责。

### 4.2 可再生成的本地文件

- `.venv/`
- `.pytest_cache/`
- 所有 `__pycache__/`
- 所有 `.pyc` 文件

这些文件不进入 Git，删除后可由依赖安装或测试重新生成。

## 5. 明确保留

- `.env`：本地运行配置和密钥，不提交、不输出内容。
- `Dockerfile`、`docker-compose.yml`、`docker-compose.test.yml`：`start.sh` 的运行依赖。
- `Makefile`：保留开发快捷命令。
- `deploy/nginx-supplier.conf`：仍是有效的反向代理示例。
- `app/web/sample-offers.csv`：工作台下载接口正在引用。
- PostgreSQL 数据卷和当前业务数据：不执行删除或重建。

## 6. 验证与提交

1. 搜索旧文档路径，确保只在迁移说明中出现。
2. 搜索旧数据库、旧端口、旧角色和特定调用系统术语。
3. 检查 Markdown 链接目标均存在。
4. 运行 `./start.sh test`。
5. 运行 `git diff --check` 并确认 `.env` 未被跟踪。
6. 按逻辑拆分提交：先提交既有应用改造，再提交文档归档与清理；每个提交只包含确认范围内的文件。

## 7. 安全边界

- 不删除无法证明无效的源码、部署文件或业务样例。
- 不修改全局 Git 配置。
- 不提交密钥、临时密码或 `.env`。
- 不删除 PostgreSQL 卷、表、记录或迁移历史。
- 如验证发现某个待删除文件仍被运行路径引用，保留该文件并修复清理清单。
