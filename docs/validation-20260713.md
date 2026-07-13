# 2026-07-13 MVP 验收记录

## 自动检查

| 检查 | 结果 |
|---|---|
| Python 测试 | 43 passed |
| 冻结 B 站产品输入 | 20/20 通过 schema、单平台与入口路由校验 |
| 前端 ESLint | 通过，无 warning |
| Next.js production build | 通过 |
| Python compile/import | 通过 |
| Alembic PostgreSQL 离线 SQL | 通过 |
| `docker compose config --quiet` | 通过 |
| Compose 服务 | 8 个服务全部启动 |
| PostgreSQL 迁移 | `20260713_0001` 成功执行 |
| API 冒烟 | health、注册、Cookie、`/auth/me`、capabilities 通过 |
| Worker | Arq 启动并连接 Redis |
| Nginx | `/` 与 `/api/health` 均返回 200 |

测试覆盖注册登录、Cookie、未登录访问、越权、幂等、取消、重试边界、Evidence 引用、分享只读与过期、反馈模型、MiMo ASR 请求格式、Base64 大小限制和 URL 白名单。自动测试未调用真实 LLM 或 ASR。

## 浏览器视觉验收

使用真实浏览器检查：

- 1440×900：首页与 Dashboard 无横向溢出
- 1024×768：首页布局正常，无横向溢出
- 390×844：首页、注册、Dashboard、新建任务无横向溢出
- 手机端主标题 36px，公共导航折叠，工作台显示移动菜单
- 注册成功跳转 Dashboard
- 深色与浅色主题切换正常，Logo 在两种背景均为 36px 清晰显示
- 工作台不再显示公开站“登录/免费试用”动作
- 浏览器控制台无页面错误

截图：

- `output/playwright/home-desktop.png`
- `output/playwright/home-mobile.png`
- `output/playwright/dashboard-desktop.png`

## 尚未伪造的线上指标

本轮没有在自动测试中消耗真实 MiMo 额度，因此以下指标必须在真实小规模测试后填写：

- 真实任务完成率
- p50 / p95 总耗时
- 每任务 LLM 调用次数
- Evidence 覆盖率与报告验证失败率
- MiMo ASR 成功率
- 用户可见错误分布

20 条冻结任务目前只证明产品输入、单平台边界和确定性入口可回归，不等同 20 次真实端到端报告完成率。
