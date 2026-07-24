# lab-modbus-mcp

[lab-executor-mcp](https://github.com/TECTOS-JP/lab-executor-mcp) 用の
Modbus RTU / TCP 計測器 backend パッケージです。

## 状況

MB-3 では薄い MCP CLI、CI と Trusted Publishing workflow、および
experimental な OMRON E5CC reference 定義と ramp/hold recipe を追加しました。
MB-2 は pymodbus 3.x を通じて非同期の Modbus TCP / RTU transport を提供します。
接続は遅延して開かれ、通信が失敗するか `close()` が呼び出されるまで再利用されます。

## 3つの利用モード

### A: backend 単体

`ModbusBackend` は lab-executor の `InstrumentBackend` protocol を実装しており、
別の Python application に注入できます。これは低水準モードです。呼び出し側が
独自の command allowlist と値の範囲に関する policy を適用する必要があります。

```python
from lab_modbus_mcp import ModbusBackend

backend = ModbusBackend(resources=["MODBUS::COM3::1"])
value = await backend.query("MODBUS::COM3::1", "RH 8192 s16 s0.1")
backend.close()
```

### B: 単独の MCP server

CLI は公開 BEF server contract (`compose_server` と `run_mcp_with_control`)
のみを使用します。`--control-port 0` を指定すると、localhost の control port を
OS が選択します。`--dry-run` は bus に接続せず構成を行い、利用可能な MCP tools
を表示します。

```console
lab-modbus serve --resource MODBUS::COM3::1 --baudrate 9600 --parity E
lab-modbus serve --resource MODBUS::192.168.0.10::502::1 --dry-run
```

### C: 統合された lab の一部

インストールすると `modbus` backend entry point が登録されます。lab-executor は
これを検出し、`CompositeBackend` を通じて VISA または別の backend と組み合わせられます。
大文字小文字を区別する `MODBUS::` prefix がこの backend を選択します。

```yaml
# instruments/_system.yaml
backends:
  visa: {}
  modbus:
    resources:
      - "MODBUS::COM3::1"
    baudrate: 9600
    bytesize: 8
    parity: "E"
    stopbits: 1
```

## wire command の形式

既存の instrument definition の `scpi` field に、整形済みの Modbus wire command
を格納します。lab-executor は protocol に依存せず、backend を呼び出す前に
parameter の範囲と capability を引き続き強制します。

```text
RH <addr> <type> [s<scale>]
RI <addr> <type> [s<scale>]
RC <addr>
RD <addr>
WH <addr> <type> [s<scale>] <value>
WC <addr> <0|1>
```

register type は `u16`、`s16`、`u32be`、`u32le`、`s32be`、`s32le`、
`float32be`、`float32le` です。すべての 32-bit type は word order を明示的に
宣言する必要があります。曖昧な `u32`、`s32`、`float32` は拒否されます。
`be` は high-word first、`le` は low-word first です。各 16-bit register 内の
byte は Modbus big-endian order を維持します。

読み取り時の scale は、すべての type で `raw * scale` です。書き込み時、integer
register type は Python の ties-to-even `round` による
`round(value / scale)` を使用します。一方、float32 type は小数値を保持するため、
丸めずに `value / scale` を使用します。既定の scale は 1.0 です。未知の token、
余分な引数、欠落した値、非有限数、範囲外の address は fail-closed で拒否されます。

## resource 名

```text
MODBUS::COM3::1
MODBUS::/dev/ttyUSB0::1
MODBUS::192.168.0.10::502::1
```

最初の2形式は RTU、3番目は TCP です。Unit ID は 1–247 に制限されます。
TCP port は 1–65535 です。entry point が受け持つのは `MODBUS::` prefix だけです。

## mock backend

低水準 codec test 用に raw 16-bit register map を注入できます。read command を
key に使うと、論理的な初期値と type、scale をまとめて注入できます。

```python
from lab_modbus_mcp import MockModbusBackend

backend = MockModbusBackend(
    initial_values={
        "RH 0 u16 s0.1": 25.0,
        "RI 10 s16": -4,
        "RC 20": True,
    }
)
```

mock には独立した raw-write helper や register-write helper はありません。
その Protocol の `write()` が受け付けるのは `WH` と `WC` だけです。本番利用では、
宣言済みの `type: write` instrument command を通じて呼び出し、lab-executor が
既存の range gate と capability gate を実行するようにしてください。backend
Protocol 自体は、その安全境界を代替するものではありません。

BEF conformance kit に限り、mock は正確な `*IDN?` と `CONF` probe を副作用のない
操作として認識します。無効化するには `allow_conformance_probes=False` を渡します。
通常の wire parser と実 backend は、どちらも拒否します。

## transport 設定

entry-point 設定は次の key を受け付けます。未知の key は拒否されます。

| key | default | 意味 |
|---|---:|---|
| `resources` | `[]` | 設定済み RTU/TCP resource 名。bus scan は行いません |
| `read_retries` | `1` | read の通信失敗後に行う retry の回数 |
| `baudrate` | `9600` | RTU baud rate |
| `bytesize` | `8` | RTU data bits (5–8) |
| `parity` | `N` | RTU parity (`N`、`E`、`O`) |
| `stopbits` | `1` | RTU stop bits (1、1.5、2) |

serial 設定は、その backend instance に設定されたすべての RTU port に適用されます。
TCP resource は resource 名から host と port を取得します。

```python
registration = make_backend(
    {
        "resources": [
            "MODBUS::COM3::1",
            "MODBUS::192.168.0.10::502::2",
        ],
        "read_retries": 1,
        "baudrate": 19200,
        "bytesize": 8,
        "parity": "E",
        "stopbits": 1,
    }
)
```

各 `query()` / `write()` 呼び出しは、それぞれの `timeout_ms` を強制します。
通信が失敗すると該当する接続を閉じ、次回の試行時に再接続します。read は
`read_retries` に従って retry する場合があります。timeout 後に結果が不明な場合でも、
write は自動 retry しません。同じ物理動作を2回適用する可能性があるためです。
32-bit write は常に、両方の word を含む1つの `write_registers` request として送信します。

transaction は物理 bus ごとに直列化されます。RTU は `serial_port`、TCP は
`host:tcp_port` を使用します。複数の unit が1本の serial line または gateway
connection を共有できるため、Unit ID は意図的に lock key に含めません。明示的な
Modbus exception response は、timeout、disconnect、CRC、framing の通信失敗とは
分けて報告され、retry されません。

`close()` は同期的かつ冪等で、best-effort です。呼び出すと、その backend instance
を通じた新しい I/O ができなくなります。

## entry point の登録

パッケージをインストールすると、次が登録されます。

```toml
[project.entry-points."lab_executor.backends"]
modbus = "lab_modbus_mcp.discovery:make_backend"
```

`make_backend(config)` は `BackendRegistration(prefixes=("MODBUS::",))` を返し、
上記の transport 設定だけを受け付けます。

## RTU の検証範囲

自動 test では、RTU client の構築、設定された serial parameter、unit-ID の転送、
serial-port lock の共有を検証します。CI では serial adapter も field device も
利用できないため、物理 RTU 通信を検証済みとはしません。TCP の検証では loopback
socket 上の実際の pymodbus asynchronous server を使用し、protocol framing、
すべての register type、scaling、coil、discrete/input read を実行します。

## 同梱の OMRON E5CC reference 定義

パッケージには `builtin_instruments/omron_e5cc_2byte_01c.yaml` が含まれます。
これは OMRON が公開している **E5[]C Digital Temperature Controllers
Communications Manual, H175-E1-18** の section 4-4-3 と 5-1 だけに基づいています。

- PV: two-byte-mode address `0x2000`
- internal SP: two-byte-mode address `0x2002`
- writable SP: two-byte-mode address `0x2103`
- RUN/STOP: operation-command address `0x0000`, values `0x0100` / `0x0101`

出典: <https://www.omron-ap.com/data_pdf/mnu/h175-e1-18_e5_c.pdf?id=3102>

文書化されていない register address は推測していません。この profile は意図的に
two-byte Modbus mode と小数点設定1桁 (`0.1 degC`) を前提としています。
`0..400 degC` の SP range は保守的な template application limit であり、
すべての E5CC sensor に共通する range ではありません。使用前に、対象の正確な
model が RS-485 をサポートすることを確認し、communications writing を有効化し、
mode、decimal point、sensor range、limit、wiring、fail-safe hardware を検証してください。

この定義は manual から作成され、hardware では未検証のため、
`metadata.support_level: experimental` を宣言しています。description にも、
register address の確認が必要であることを記載しています。対象 hardware で
identify、command、state query、verification、safe shutdown のすべてを確認するまで、
support level を `verified` に変更しないでください。

同梱の `temperature_ramp_and_hold_reference` recipe は SP を段階的に write し、
`wait_for_stable` で安定を待ってから hold します。明示的な template resource として
`MODBUS::COM3::1` を使用しているため、実際の resource と thermal process に合わせて
調整する必要があります。これは reference であり、検証済みの thermal profile ではありません。

## 安全性

- lab-executor を通じて書き込み可能な register は、名前付き instrument command
  として公開する必要があります。同梱の E5CC 定義が公開するのは SP と文書化済みの
  RUN/STOP 操作だけで、可変 SP 引数には range が必須です。
- 低水準 backend は、任意の wire command を安全な device policy に変換しません。
  モード A の呼び出し側は、同等の allowlist と range を強制する必要があります。
- write は自動 retry しないため、結果不明の操作が2回適用されることを防ぎます。
- すべての 32-bit 値は、1回の multi-register transaction で転送されます。
- bus access は serial port または TCP host/port ごとに直列化されます。
- 同梱の定義は hardware 未検証で、`experimental` と明記されています。

## 開発

```console
python -m pytest -q
ruff check src tests
ruff format --check src tests
python -m build
python -m twine check dist/*
```

## ライセンス

MIT
