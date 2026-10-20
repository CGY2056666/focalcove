# 评测说明

本目录只包含评测流程说明，**不附带任何真实截图、目标文本或人工标注**。仓库中的
`evaluation/` 在公开版本里为空（除本文件），运行采集后写入的样本已被 `.gitignore`
排除。

## 数据边界

- 评测样本可能包含个人信息、工作内容或聊天画面。采集前必须取得参与者明确同意。
- 不要采集密码、支付、证件、私密聊天或受保密协议约束的内容。
- 样本只保存在本地或受控存储中，不要提交到 Git、Issue、Pull Request 或公开网盘。
- 采集默认关闭。开启后会把原始目标文本与截图写入磁盘，且没有自动过期策略；请自行
  设定保留期限并在结束后手动清理。

## 目录约定

采集器默认写入 `FOCUS_EVAL_CAPTURE_DIR`（默认 `evaluation/inbox`）：

```text
evaluation/inbox/
  <sha256>.jpg
  <sha256>.json      # 同一 id 的元数据
```

整理评测集时，按人工标签把样本复制到四个状态目录：

```text
evaluation/dataset/
  focused/
  uncertain/
  distracted/
  unscorable/
```

不要用模型输出代替人工标签；`evaluate_vision_results.py` 会把 `ai`、
`ai_reference`、`model_generated` 等来源视为参考而非真值。

## 流程

1. **采集**：设置 `FOCUS_EVAL_CAPTURE_ENABLED=true`，在明确同意后运行专注会话。
   检查生成的 JSON 元数据是否完整，删除不合格样本。
2. **人工标注**：由至少一名人工标注者按评分维度标注四态。标注者应能看到目标文本，
   但不应看到模型结果，以避免锚定。
3. **复核**：抽样复核标签一致性；有争议的样本单独记录，不强行合并。
4. **生成清单**：`python scripts/build_vision_manifest.py --help`
5. **模型基准**：`python scripts/benchmark_vision_models.py --help`。该步骤会调用真实
   外部模型并产生费用。
6. **汇总评估**：`python scripts/evaluate_vision_results.py --help`。脚本包含原型发布
   门槛（例如最少样本数与每类最少样本数）。
7. **超时对比**：`python scripts/compare_timeout_results.py --help`
8. **策略调优**：`python scripts/tune_scoring_policy.py --help`。该脚本只使用完整人工
   标注，不调用外部 API，也不会改变分类阈值。

## 发布门槛与解释

- 样本量不足、类别不均衡或标注来源不可靠时，不得据此宣称模型“准确率”。
- 分数表示画面与文字目标的相关证据，不是注意力或任务质量的测量。
- 调参结果必须经过独立留出集验证；不要用同一批样本既调参又报告最终指标。
- 任何发布说明都应同时给出样本来源、标注流程、排除标准与已知偏差。

## 成本与合规

外部视觉模型按调用计费。批量评测前先估算调用次数与费用，并使用受控密钥。你还需要
遵守模型提供方的条款、当地隐私法规以及所在机构的伦理审查要求。
