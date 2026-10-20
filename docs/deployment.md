# Android MVP 后端部署

面向移动接口的旁路部署、Nginx 配置、备份、回滚和冒烟步骤见
`deploy/example/README.md`。该流程不影响网页版，只新增 `/api/v1/` 路由。

该部署只支持一个 Gunicorn worker；活动专注会话保存在该进程内存中，容器重启后不会恢复，客户端应把服务端 `404 session_not_found` 显示为“本轮因服务重启未完整保存”。

## 持久数据

把宿主机的全新空目录挂载到 `/app/runtime`。该目录保存 `users.json`、`mobile_sessions.json`、`user_data/` 和 `user_history/`，不要把开发机现有账号、历史或 `.env` 打入镜像。

## 环境与启动

至少设置：

- `FOCUS_APP_SECRET`：随机生成且不得使用示例值。
- 当前视觉提供方所需的服务端 API Key；Key 不得写入 Android 客户端。
- `FOCUS_EVAL_CAPTURE_ENABLED=false`，避免保存用户截图。

构建并运行镜像后，由支持 HTTPS 的反向代理转发到容器 `8000` 端口。该端口只能暴露在内部容器网络，不能直接发布到公网。代理必须先删除客户端传入的 `Forwarded`、`X-Forwarded-For`、`X-Forwarded-Proto` 和 `X-Forwarded-Host`，再由代理自身设置可信的 `X-Forwarded-For` 与 `X-Forwarded-Proto: https`。

镜像默认设置 `FOCUS_TRUST_PROXY_HEADERS=true`，且应用只信任一层 `X-Forwarded-For` 和 `X-Forwarded-Proto`，不会信任 `X-Forwarded-Host`。如果进程没有位于上述受控代理之后，必须把该变量设为 `false`。生产模式会拒绝除 `/health` 外的明文 HTTP 请求。运行命令固定为一个 worker 加四个线程，不能横向增加 worker，否则活动会话会落到不同进程。

最小可复现的容器启动命令如下；故意不使用 `-p` 暴露端口，HTTPS 反向代理必须与它加入同一个内部 Docker 网络：

```powershell
docker build -t focus-compass:android-mvp .
docker network create focus-internal
docker volume create focus-compass-runtime
docker run --rm --name focus-compass --network focus-internal -v focus-compass-runtime:/app/runtime --env-file .env.production focus-compass:android-mvp
```

镜像进程以固定 UID/GID `65534:65534` 运行，只对 `/app/runtime` 有写权限。使用空的 Docker named volume 时会继承镜像目录权限；若改用宿主机 bind mount，必须预先把该目录授权给 `65534:65534`。反向代理的上游地址使用 `focus-compass:8000`，对外域名和证书需由部署者提供，完成后再用该真实 HTTPS 地址构建 Android APK。

移动接口默认使用进程内滑动窗口限流：注册和登录按来源 IP 限制为每 60 秒 20 次，截图上传按用户名和会话限制为每 60 秒 6 次。可分别通过 `MOBILE_AUTH_RATE_LIMIT`、`MOBILE_AUTH_RATE_WINDOW_SECONDS`、`MOBILE_FRAME_RATE_LIMIT` 和 `MOBILE_FRAME_RATE_WINDOW_SECONDS` 调整。

截图由请求内存直接进入分析器；服务端不需要也不应为移动截图创建落盘目录。持久卷与日志的访问权限应限制在服务账号。

移动 JSON 响应统一带有 `Cache-Control: no-store`；生产 `/health`
只返回最小服务状态。生产启动还会拒绝使用源码目录中的默认 JSON 路径，
避免部署时误用开发账号和历史。
