## 变更说明

简要描述本次改动解决什么问题。

## 变更类型

- [ ] 修复 bug（fix）
- [ ] 新功能（feat）
- [ ] 文档（docs）
- [ ] 重构（refactor）
- [ ] 其它（chore / test / build）

## 测试

- [ ] `scripts/ci_parity.sh` 通过（等价于 CI 的
      `python3 -m unittest discover -s tests -p 'test_*.py'`；脚本会核对 skipped 数，
      确认 `node` 在 PATH 上，避免渲染护栏用例被静默跳过）
- [ ] 涉及 GUI/CLI 结论时，`scripts/verify_gui_consistency.sh` 通过
- [ ] 桌面 App 改动已本地构建验证（如有）

## 检查项

- [ ] 未提交个人拓扑 / 真实端点 / 密钥（`config.yaml` 保持通用占位）
- [ ] 写操作遵循「备份 → 原子写 → 校验 → 回滚」安全链
- [ ] 相关文档已同步更新（见 `docs/README.md`）

## 关联

Closes #<issue>
