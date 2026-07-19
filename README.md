# lab-modbus-mcp

Modbus RTU / TCP backend for [lab-executor-mcp](https://github.com/TECTOS-JP/lab-executor-mcp).

温調器・チラーなど Modbus 機器を、YAML で定義したコマンドから制御します。

> **状態: 実装着手前（骨子のみ）**
> 仕様は `docs/` に置かれる実装計画と、AutoLaboKnowlege の
> `lab_modbus_mcp_spec.html`（仕様検討書）を参照してください。

## 位置づけ

`lab-executor-mcp` の `InstrumentBackend` を実装する **機器バックエンド** です。
ランタイム（レシピ・安全層・実験資産）は `lab-executor-mcp` 側が持ち、
本パッケージは Modbus の通信と、レジスタ操作のワイヤコマンド解釈のみを担当します。

## ライセンス

MIT
