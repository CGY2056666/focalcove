# 专注小窝 Android 2.0

原生 Android 客户端，包名为 `com.focuscompass.app`，支持 Android 10（API 29）及以上。
客户端通过 HTTPS 连接自建的 Flask 服务，并使用与 Web 端相同的评分引擎。

> 2.0 仅更新版本号，功能与 0.6.0 相同。

## 功能概览

- “我的”内置原生“使用说明”，覆盖快速开始、四态与报告、整屏共享和隐私、积分小窝、
  常见问题以及开源许可；页面不使用 WebView。
- 连续两次采集到近黑画面时，客户端将其作为采集健康异常：跳过图片编码和上传、只发送
  一次高优先级提醒，并明确说明这不等于分心。
- 专注页可重新发起系统整屏共享授权；授权成功后继续原服务端会话和原倒计时，不创建
  新会话。已经到期的会话只执行幂等结算，不会用旧数据复活倒计时。
- 底部导航为“首页／小窝／记录／我的”，小窝使用 Compose 原生界面。
- 小窝读取当前账号的积分、已拥有家具和房间配置；支持日夜氛围、地板、墙面和 8 个
  独立家具位置。
- 家具商店只展示服务端真实可兑换的虚拟家具；兑换前确认，成功后可立即摆放，重复
  请求不会重复扣分。会员和礼券仅作预览，不可兑换。
- 记录页显示最近 7 天完成轮次、最近 10 次可靠评分、有效覆盖率变化和可靠记录明确
  判定时段构成。
- 每条历史记录均可进入原生报告页，查看目标、完成时间、计划时长、得分、积分、
  有效覆盖率、专注/分心估算时长和服务器总结。
- 低覆盖率或未通过可靠性检查的历史报告突出显示“仅供参考”，不按普通成绩解释。
- 分析只描述当前加载的最近最多 50 条；计划时长不作为实际专注时长，评分趋势不解释为
  注意力改善或下降。

## 构建

需要 JDK 17、Android SDK Platform/Build Tools 36 和 Gradle 8.11.1。服务器地址必须是
HTTPS，并在构建时提供：

```powershell
.\gradlew.bat -PFOCUS_API_BASE_URL=https://your-domain.example/ testDebugUnitTest assembleDebug
```

未设置时使用 `https://example.invalid/`，该地址故意不可连接，避免测试包误传截图。
调试 APK 输出到 `app/build/outputs/apk/debug/app-debug.apk`。
构建会拒绝 HTTP、缺少主机名、包含账号密码、查询参数或片段的服务器地址。

如果仓库路径含中文或空格，Windows 上的 Gradle 测试进程可能错误解码类路径。建议把
检出目录放在纯 ASCII 路径下再构建。

发布构建可运行 `assembleRelease`，签名参数通过本机 Gradle 配置或环境变量注入。
请自行创建并安全备份 keystore；不要把 keystore、口令、模型 API Key 或真实服务器
密钥提交到仓库。调试签名仅用于本地安装，不用于应用商店发布。

安装到已开启 USB 调试的手机：

```powershell
adb install -r app\build\outputs\apk\debug\app-debug.apk
```

## 服务端接口

客户端使用 `/api/v1/` 下的版本化 JSON 接口，包括认证、bootstrap、会话、历史、小窝和
兑换。接口由本仓库的 Flask 应用提供：

- `GET/PUT /api/v1/den`
- `POST /api/v1/shop/exchanges`
- `POST /api/v1/auth/*`、`GET /api/v1/bootstrap`、`GET /api/v1/history`
- `POST /api/v1/focus-sessions`、`GET /api/v1/focus-sessions/{id}`、
  `POST /api/v1/focus-sessions/{id}/frames`、`POST /api/v1/focus-sessions/{id}/complete`

部署方式见 [`../deploy/example/README.md`](../deploy/example/README.md) 和
[`../docs/deployment.md`](../docs/deployment.md)。

## 隐私与运行约束

- 每轮都需要用户勾选截图处理确认，并重新通过系统 MediaProjection 授权。
- 客户端只在内存中压缩当前帧，不把截图写入文件或 DataStore，也不补传失败帧。
- 截图会通过 HTTPS 发送到自建服务器，再由服务器配置的第三方视觉模型分析。不要在
  专注期间展示密码、支付、证件或私聊等敏感内容。
- 登录令牌由 Android Keystore AES/GCM 加密后存入私有 SharedPreferences。
- DataStore 仅保存隐私同意、提醒声音和活动会话 ID。
- Manifest 禁止明文 HTTP；模型 API Key 只应配置在服务端。
- 部分设备在系统“录屏投屏”通知中选择“禁止”后，仍可能向应用提供近乎全黑画面，而不是
  触发标准 `MediaProjection.Callback.onStop()`。应用在连续两次确认后跳过这些画面，
  不编码、不上传、不补传，也不判定为分心；用户可重新授权并继续原会话。需要可靠结束
  时仍应使用专注小窝自己的“结束本轮”入口。
- 小窝与兑换只保存物品 ID、积分和布局配置，不保存图片、截图或模型响应。

## 许可

Android 客户端以 Apache License 2.0 发布。场景图、品牌标志、launcher 与家具矢量资源
的版权与许可说明见 [`ASSET_NOTICES.md`](ASSET_NOTICES.md)；第三方组件见
[`../THIRD_PARTY_NOTICES.md`](../THIRD_PARTY_NOTICES.md)。安装包内也附带
`LICENSE`、`NOTICE` 与 `THIRD_PARTY_NOTICES.md`，可在“使用说明 → 开源许可全文”中查看。
