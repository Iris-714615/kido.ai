# 儿童端

本目录是 KidoAI 的儿童端静态页面。

## 本地打开

先启动后端：

```bash
cd services/api
uvicorn app.main:app --reload --port 8000
```

再打开静态页面：

```bash
cd apps/child-web
python -m http.server 5173
```

访问：

- 前端: `http://localhost:5173`
- 后端: `http://localhost:8000`

