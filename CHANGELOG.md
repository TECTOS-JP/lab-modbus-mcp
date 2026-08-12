# Changelog

## Unreleased

### 同梱の機器定義を実行時に結び付ける (明示指定のみ)

`builtin_instruments/*.yaml` は同梱されていたが、実行時に使う経路が無かった。
`compose_server(backend)` を呼ぶだけで session を渡していなかったため、設定済みの
機器が `describe_instrument` / `get_instrument_info` / `get_state` のいずれからも
「未識別」と報告されていた (実プロセスで確認)。

他の backend と違い、**この結び付けは推測できない**。BLE は resource 名に profile
を含み、NI-DAQ は設定の model を初回ハードウェア接触時に照合する。Modbus の
resource 名はポートと unit id だけで、その先に何があるかを示さず、protocol 側も
誤りを教えてくれない。誤った定義を結び付ければ、その機器では別の意味を持つ
レジスタアドレスへ書き込むことになる。したがって**明示指定がなければ結び付けない**。

- `sessions.py` を追加。`{resource: 定義名}` の明示マッピングだけを解決する。
- `serve --instrument RESOURCE=DEFINITION` を追加 (繰り返し可)。
- 存在しない定義名は skip せず error にする。skip すると利用者が結び付いたと
  誤解するため。

実機確認: `--instrument "MODBUS::COM9::1=omron_e5cc_2byte_01c"` を指定すると
OMRON E5CC として認識され、`list_commands` が 5 件を種別付きで返す。

### CI の ruff 失敗を修正

CI は `ruff>=0.8` を pin せず 0.16.0 を導入するため、新しい規則で既存コードが
22 件引っかかり main の CI が失敗していた。18 件は自動修正。残る 4 件は
意図的な実装なので理由を添えて noqa とした (close() の best-effort な握り潰しと、
検証エラーに ValueError を使うパッケージの規約)。

## Unreleased

### Added

- MB-1 package skeleton for `lab-modbus-mcp` 0.1.0.
- Strict parsers for `MODBUS::` RTU/TCP resources and RH/RI/RC/RD/WH/WC wire
  commands.
- Register codecs for u16/s16 and explicit big-/little-word-order 32-bit integer
  and float types, plus deterministic type-specific scale handling.
- In-memory `MockModbusBackend` with injectable register/bit maps and logical
  initial values.
- Importable, unconnected `ModbusBackend` skeleton for the MB-2 transport seam.
- `lab_executor.backends` entry-point registration with `MODBUS::` ownership.
- BEF backend-conformance, fail-closed grammar, round-trip, word-order,
  resource-parser, discovery, and packaging tests.
- MB-2 asynchronous pymodbus 3.x transport for configured TCP and RTU
  resources, with lazy reusable connections and synchronous idempotent close.
- Physical-bus transaction locks, per-call timeouts, read-only configurable
  retries, explicit exception-response errors, and atomic 32-bit writes.
- Real-loopback pymodbus TCP integration tests plus isolated RTU construction,
  parameter-forwarding, and serial-port-lock tests.
- MB-3 experimental OMRON E5CC two-byte/0.1-degree reference definition with
  documented-only PV, internal-SP, SP-write, and RUN/STOP addresses.
- Reference temperature ramp, stability-wait, and hold recipe with mock Job
  completion coverage and safe-shutdown policy.
- Thin `lab-modbus serve` CLI using the public BEF server composition contract.
- Python 3.11 CI, BEF integration coverage, and OIDC Trusted Publishing
  workflows with distribution metadata and sdist-content guards.

### Fixed

- Preserve fractional float32 values during scaled writes; only integer
  registers apply ties-to-even rounding.
- Require explicit word order for 32-bit integers (`u32be/le`, `s32be/le`) and
  reject ambiguous bare `u32` / `s32` tokens.
- Add root `conftest.py` so local source imports work without installing this
  project; metadata-dependent entry-point tests skip clearly when uninstalled.
