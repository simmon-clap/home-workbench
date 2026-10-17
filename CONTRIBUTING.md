# 贡献指南（开发者）

- 先开 issue 说明动机，再提 PR；改动请保持"能机器验证"：带测试或带门禁证据。
- 本地检查：`python3 tools/gate.py`、`python3 tools/test_scan_room.py`、`python3 tools/release_audit.py --public-set`。
- 不要提交：`data/ config/ backups/ logs/ installers/ vm/ vendor/`、任何家庭数据、凭证、真实户型。
- 代码风格：标准库优先、单文件 ≤600 行、生成物必须带 `*.build.md`（见 `docs/spec/11`）。
- 许可证：MIT；第三方依赖保留其自身许可证并在 PR 中注明。
