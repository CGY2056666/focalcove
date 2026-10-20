# Android 视觉资产说明

本目录中的 Android 视觉资源由 FocalCove（专注小窝）团队创作，或在团队自有网页资源
基础上转换为 Android 资源。除另有说明外，以下资产随本项目按 Apache License 2.0
发布，版权归 FocalCove Team 所有（Copyright 2026 FocalCove Team）。

完整许可与商标说明见仓库根目录 [`../LICENSE`](../LICENSE)、[`../NOTICE`](../NOTICE)
和 [`../THIRD_PARTY_NOTICES.md`](../THIRD_PARTY_NOTICES.md)。

## 品牌标志

- Android 资源：`app/src/main/res/drawable/brand_mark.xml`、`ic_launcher*.xml`
- 来源：团队自有的 `static/brand-mark.svg`
- 用途：应用内品牌展示与 launcher 图标
- 许可：Apache License 2.0；商标权不随许可证授予，详见根目录 `NOTICE`

## 场景图片

| Android 资源 | 仓库来源 |
| --- | --- |
| `morning_desk.webp` | `static/images/focus-scenes/morning-desk.webp` |
| `afternoon_reading.webp` | `static/images/focus-scenes/afternoon-reading.webp` |
| `evening_workspace.webp` | `static/images/focus-scenes/evening-workspace.webp` |

这三张场景图由 FocalCove 团队创作并持有版权，随项目按 Apache License 2.0 发布。
Web 与 Android 副本内容一致，仅资源目录不同。团队内部保留创作记录。

## 小窝矢量家具

- Android 资源：`app/src/main/res/drawable/den_*.xml`
- 来源：团队自有的 `templates/_decor_icons.html` 中的基础房间样式和家具 SVG
- 转换：仅将网页 SVG 的路径、颜色、透明度和分组转换为 Android VectorDrawable
- 用途：小窝预览、已拥有装扮和家具商店
- 许可：Apache License 2.0

会员、礼券、饮品等网页预览奖励没有转换进 Android，也不能通过移动 API 兑换。若后续
引入任何第三方图标、字体或图片，必须在合并前补充来源、许可证和归属信息，并更新
`THIRD_PARTY_NOTICES.md`。
