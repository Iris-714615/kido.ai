# KidoAI

KidoAI 的第一版起步骨架。

## 启动

本地开发优先：

```bash
cd services/api
uvicorn app.main:app --reload --port 8000
```

```bash
cd apps/child-web
python -m http.server 5173
```

或者整套容器：

```bash
docker compose up --build
```

## 默认访问

- API: `http://localhost:8000`
- 前端: `http://localhost:5173`

## 演示账号

- 账号: `demo_child`
- 密码: `demo123`

<!-- 家长端： http://localhost:5174/ → 登录 parent_test / test123456 → 点击儿童卡片 → 查看"AI 成长分析"面板 -->
