# schematic-review-checker

按一套标准流程对原理图做系统性审查，输出可直接抄进 ECR 的分级问题清单——不用每次从零开始。

原理图审查/检查（Schematic Review）通用技能，面向基于 SoC 的嵌入式板卡（视频监控主控 / WiFi / USB / SDIO / DDR / 传感器）。

对硬件原理图做**基于网表 + DRC + PIN mux + 用户指南**的系统性审查，输出定位到位号 / 网络 / ball 号的分级问题清单，可直接抄进 ECR。

> 本仓库是 WorkBuddy 的用户级 Skill（`~/.workbuddy/skills/schematic-review-checker/`），也可作为一套独立的原理图检查方法论与脚本使用。

---

## 为什么需要它

原理图检查最容易出问题的地方不是"看不出来"，而是**没有稳定、可复用的检查顺序**，导致：

- 只顾查外设功能，漏掉"能不能开机"的致命项；
- 把网络标签当成引脚功能，误判复用冲突；
- 迷信 DRC"没报错"，漏掉经磁珠供电、关键 NC 脚等 DRC 识别不了的问题；
- 看到元件标 `/NC` 就报"strap 悬空"，其实是不贴装、由内部上下拉定电平。

这个技能把这些经验固化成**清单 + 脚本 + 工作流**，保证每次检查不漏项、不误判。

---

## 能检查什么

### ★ 启动链路（最高优先级）
开机触发脚 / 复位（极性、脉宽、POR_SEL）/ 主晶振与 RTC 晶振 / boot strap / 常电域（AVDD_BAT、PMC）/ IO 电压域软硬件一致性 / DDR 初始化条件。

### 其他检查域
| 域 | 内容 |
|---|---|
| 电源 | DC-DC/LDO 反馈电阻反算、自举电容、EN 上拉、输入/输出电容、驱动源、电源短路、上电时序、去耦 |
| PIN mux 复用 | 引脚 pinname 合法性、同 ball 多网络硬冲突、pinname 与网络名暗示功能的矛盾、接口组功能号一致性 |
| 单点网/无驱动源 | single node net、no driving source 的成因甄别 |
| 信号完整性与防护 | USB/SDIO/DDR 端接匹配、差分阻抗、TVS/ESD、包地 |
| 上下拉与未用脚 | 悬空输入、开漏上拉、SPI CS、NC/ strap 脚处理 |
| DRC/ERC 告警 | 识别真实电气错误与库定义噪声（如 ORCAP-1829） |

输出按 **P1 致命 / P2 严重 / P3 建议** 分级，附检查通过项、局限说明、行动清单。

---

## 文件结构

```
schematic-review-checker/
├── SKILL.md              # 工作流主文档 + 踩坑经验（技能入口）
├── CHECKLIST.md          # 完整检查清单（第 0 节启动链路★）
├── REPORT_TEMPLATE.md    # 报告输出模板
├── README.md             # 本文件
└── scripts/
    ├── netlist_audit.py  # 网表 + DRC 通用检查脚本（纯标准库）
    └── pinmux_check.py   # PIN mux 复用核对脚本（纯标准库）
```

两个脚本均为 **Python 纯标准库**，无需 pip 安装依赖。

---

## 快速开始

### 作为 WorkBuddy Skill 使用（推荐）

把本仓库放到 `~/.workbuddy/skills/schematic-review-checker/`，然后在对话中给出板卡资料并说"检查这块板的原理图"，即可自动加载技能并按工作流执行。

### 手动运行脚本

```bash
# 1. 网表 + DRC 检查（allegro 目录需含 pstxnet/pstxprt/pstchip）
python scripts/netlist_audit.py <allegro目录> --drc <报告.DRC> --out <输出目录>

# 2. PIN mux 复用核对（两个 json 分别由网表解析与 PIN mux 表提取得到）
python scripts/pinmux_check.py <netlist_db.json> <pinmux_db.json> --soc-ref U11 --out <输出目录>
```

---

## 输入材料

| 材料 | 用途 | 必需 |
|---|---|---|
| `pstxnet.dat` / `pstxprt.dat` / `pstchip.dat`（Allegro 网表三件套） | 网络拓扑、元件值、引脚定义 | ✅ |
| `*.DRC`（OrCAD 设计规则检查报告） | ERC 告警、单点网、无驱动源 | 推荐 |
| 芯片 PIN OUT / PIN mux 表（`.xlsx`） | 引脚复用合法性、冲突判断 | 推荐 |
| SoC 用户指南 / 硬件设计指南（`.pdf`） | 启动条件、复位时序、电压域、strap 定义 | 推荐 |
| BOM | 确认 NC/0R 位实际贴装 | 可选但重要 |

---

## 关键经验：strap 电平核查三步法

这是实战中踩坑后固化的方法，**不要看到 `/NC` 就报"strap 悬空"**：

1. **先判贴装**：元件值带 `/NC` = 不贴装（DNI），不是悬空/不确定。
2. **再查内部默认**：查 PIN mux 表「管脚默认状态」，看该 pin 复位释放前的 Level State：`PD`=内部下拉、`PU`=内部上拉、`Z`=高阻。strap 电阻不贴时电平由内部上下拉决定。
3. **外部实贴电阻优先**：若有实贴（无 NC）的外部上/下拉，其阻值远小于内部弱上下拉，会压过内部默认值决定最终电平。
4. **对照编码表定性**：查指南 SYSSTAT 类寄存器确认 boot_sel / update_mode 编码；判断外接器件是输入高阻（通常无害）还是输出源（可能干扰）。
5. **核对启动 Flash 真型**：符号名可能与封装型号矛盾（如 `SPI_NAND_FLASH_1` 型号却是 `MX25L128` = SPI NOR），以型号为准。

更多踩坑与判断原则见 `SKILL.md` 与 `CHECKLIST.md`。

---

## 权衡与局限

- 基于网表的检查无法验证 PCB 阻抗、走线长度、焊接、上电时序实测波形。
- 所有 `/NC` 与 0R 位高度依赖 BOM 实贴值，无 BOM 时标"需确认"而非直接判错。
- IO 电压域的软件配置（uboot/驱动）不在原理图内，需软件侧确认。

---

*本技能由一次 GK7205V13 WiFi 板卡原理图审查实战沉淀而来，并持续迭代。*
