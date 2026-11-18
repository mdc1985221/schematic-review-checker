---
name: schematic-review-checker
description: |
  原理图审查/检查（Schematic Review）通用技能，面向基于 SoC 的嵌入式板卡（视频监控主控/WiFi/USB/SDIO/DDR/传感器）。
  输入 Allegro 网表三件套(pstxnet/pstxprt/pstchip)、OrCAD DRC 报告、芯片 PIN mux 表(XLSX)、SoC 用户指南(PDF)，
  输出分级问题清单。检查覆盖：启动链路(开机脚/复位/晶振/boot strap/IO电压域/DDR初始化)★、电源(反馈/自举/驱动源/时序)、
  PIN mux 复用冲突、单点网络/无驱动源、外设(WiFi/USB/SD/ESD)、DRC 告警处理。
  触发词：原理图检查、原理图审查、schematic review、网表检查、检查复用冲突、检查单点网络、电源驱动源检查、能不能开机检查。
agent_created: true
---

# 原理图审查检查器（Schematic Review Checker）

对硬件原理图做**基于网表 + DRC + PIN mux + 用户指南**的系统性审查，输出定位到位号/网络的分级问题清单。

## 核心原则（血泪经验）

1. **先查"能不能开机"，再查功能**——启动链路问题（开机脚接 NC、常电域接错、boot strap 错、IO 电压域软件硬件不一致）是致命项，功能再对也白搭。见 CHECKLIST.md 第 0 节。
2. **网络名 ≠ 引脚功能**：网表里的 pinname 来自符号（symbol），网络名是连线标签。两者不一致时（如 pinname=SDIO1_CMD 但网络名含 LCD_DATA21/PWM5）往往是复用配置风险，必须查 PIN mux 表。
3. **DRC 不报错 ≠ 没问题**：OrCAD 的驱动源/引脚类型检查依赖库定义，经磁珠传递的电源、NC 的关键脚它都识别不了。必须结合网表独立核查。
4. **分级输出**：P1 致命（不开机/损坏风险）→ P2 严重（功能/可靠性）→ P3 建议（优化），附"检查通过项"与"局限说明"。

## 输入材料（尽量齐全）

| 材料 | 用途 | 必需 |
|---|---|---|
| `pstxnet.dat` / `pstxprt.dat` / `pstchip.dat`（Allegro 网表三件套，同目录） | 网络拓扑、元件值、引脚定义 | ✅ |
| `*.DRC`（OrCAD 设计规则检查报告） | ERC 告警、单点网、无驱动源 | 推荐 |
| 芯片 PIN OUT / PIN mux 表（`.xlsx`） | 引脚复用合法性、冲突判断 | 推荐 |
| SoC 用户指南 / 硬件设计指南（`.pdf`） | 启动条件、复位时序、电压域、 strap 定义 | 推荐 |
| BOM | 确认 NC/0R 位实际贴装 | 可选但重要 |

## 工作流

### Step 0：确认材料与工作目录
把所有材料路径记下来；在会话工作区建 `review_out/` 放中间结果。

### Step 1：解析网表三件套
用 `scripts/netlist_audit.py`（本 skill 自带，纯标准库）：

```bash
python <skill_dir>/scripts/netlist_audit.py <allegro目录> --drc <xxx.DRC> --out <review_out目录>
```

产出 `audit_result.json`：网络数/节点数、单节点网络、启发式无驱动电源网、DRC 的 1600/1608 告警。
脚本会自动解析 pstxnet(网络/节点) + pstxprt(元件值) + pstchip(引脚定义)。

> 踩坑：`pstxnet.dat` 里实例路径是 `:INS\d+@LIB.PART.NORMAL`（INS 前是**冒号**不是 @），正则写错会导致节点解析为 0。

### Step 2：查启动链路（最高优先级）★
打开 SoC 用户指南 PDF（用 workbuddy-pdf skill 的 `run.sh`，`-f md` 提取），关键词定位：
`复位 / PWR_BUTTON / PWR_STARTUP / boot_sel / 启动模式 / 上电 / 晶振 / XIN / 电压域 / DVDD3318 / DDR`

把指南里的**硬性要求**逐条对照网表：
- 开机触发脚是否接了可用电路（按键/上拉），接 NC 的要告警
- 开机脚是否被复用为 GPIO/PWM（查 `xxx_ioshare` / `xxx_func_sel` 寄存器默认值，默认=0 通常是 PWR 功能）
- 常电域（AVDD_BAT/PMC/RTC）是否接真实常电，若接可关断电源则告警
- 复位脚/复位芯片输出是否正确，外部复位脉宽（如 ≥16ms）
- 晶振 XIN/RTC_XIN 频率、负载电容、反馈电阻；RTC 接 NC 的确认
- boot strap 上拉/下拉组合
- IO 电压域 `DVDD3318_xxx` 硬件电压 vs 软件默认值（默认多为 3.3V，硬件接 1.8V 要告警）
- DDR VREF 分压、RSTN、CKE、ZQ

### Step 3：PIN mux 复用核对
PIN mux 表是 xlsx，按 WorkBuddy 规则用 workbuddy-sheetagent / sheet-agent 读取（不要直接用 openpyxl 绕过）。
让 sheet-agent 把提取结果**落盘为 JSON**（`pinmux_db.json`：含 `balls[].functions[]{function_number,signal_name}`）；若它受权限限制无法写文件，会写进工作簿新 sheet——此时用 `mcp__sheetagent__read_table` 读出（大结果会自动存到 tool-results 文件，注意 JSON 可能被按 25000 字符切到多个 cell，按 A1:A4 顺序拼接再 `json.loads`）。

拿到 `pinmux_db.json` 后用本 skill 的 `scripts/pinmux_check.py` 自动核对：

```bash
python <skill_dir>/scripts/pinmux_check.py <netlist_db.json> <pinmux_db.json> --soc-ref U11 --out <review_out目录>
```

核对内容：
- 网表每个 SoC 引脚的 pinname 是否属于该 ball 候选功能
- 同一 ball 是否接多个网络（硬冲突）
- pinname 功能 vs 网络名暗示的其它复用功能（潜在 mux 风险）
- 同接口组（SDIO0 等）功能号一致性

补充人工判断：
1. 网表中每个用到的 ball，其 pinname 是否属于该 ball 的合法候选功能（不是则告警）
2. pinname 功能 vs 网络名暗示功能是否矛盾（矛盾则是复用风险）
3. 同一接口组（SDIO0/SDIO1/LCD/DDR）的信号功能号（Function Number）是否一致（不一致则告警）
4. 关键脚（boot/电源/时钟/USB/DDR）逐个列出候选功能与实际使用

判断复用冲突的核心：**同一物理 ball 只能同时用一个功能**；一个 pinname 若在两个不同网络出现就是硬冲突。

### Step 4：电源与外设检查
按 CHECKLIST.md 第 1、6、7 节逐条过：
- 电源：拓扑/反馈电阻计算 Vout / 自举电容 / EN 上拉 / 驱动源 / 电源域隔离 / 去耦
- 外设：WiFi 天线 π 匹配、USB D± TVS、SD 卡 TVS、ESD 防护
- 对 DRC 的 ORCAP-1829（双向引脚接电源）这类库定义噪声，识别出来并在报告里说明，不误报为电气错误

### Step 5：输出报告
结构：架构对齐 → 分级问题清单（P1/P2/P3，每条含 问题/定位/风险/建议）→ 检查通过项 → 局限说明 → 行动清单。
问题必须定位到**位号、网络名、ball 号**，可直接抄进 ECR。

## 参考文件

- `CHECKLIST.md`：完整检查清单（第 0 节启动链路★、电源、时钟、复位、上下拉、单点网、PIN mux、SI/ESD、DRC 处理）
- `scripts/netlist_audit.py`：网表+DRC 通用检查脚本（纯标准库，无需 pip）
- `REPORT_TEMPLATE.md`：报告输出模板

## 常见误判提醒

- 经磁珠/电感从上级电源引入的网络，OrCAD 会报"无驱动源"，实际正常——人工确认上级来源即可。
- `ORCAP-1829 Possible pin type conflict ... Bidirectional Connected to Power` 多为库引脚类型定义不统一，全板成百上千条时是噪声，聚焦具体电气问题。
- NC 网络里有 50+ 个节点时，那些是各个未用引脚共享的 "NC" 网，不是真的连在一起——不要报"NC 网络短路"。
- 天线匹配电容标 NC、电感值标注异常、0R/NC 位——高度依赖 BOM 实贴值，无 BOM 时标"需确认"而非直接判错。
