# PicoRV32 增强调试版本

## 概述

这是 PicoRV32 的增强调试版本，在原始代码基础上添加了详细的调试日志功能，用于跟踪：
- ✅ 寄存器写入（包含指令上下文）
- ✅ 异常事件（对齐错误、非法指令等）
- ✅ 内存写入（包含数据大小和指令信息）
- ✅ Trap 状态转换

## 快速开始

### 1. 编译调试版本

```bash
cd /home/canxin/Git/riscv_research/picorv32
make testbench_cli
```

这将编译启用了 `VERBOSE_DEBUG` 的测试台。

### 2. 运行示例程序

```bash
cd examples/skip_exception_standalone
make test-verbose
```

## 修改的文件

### 核心修改

- **picorv32.v**: 添加 `VERBOSE_DEBUG` 宏支持，在关键位置插入调试日志
  - 行 28-43: 添加 `VERBOSE_DEBUG` 宏定义
  - 行 1346: 寄存器写入日志
  - 行 1497: Trap 状态日志
  - 行 1618, 1630: 异常处理日志（非法指令）
  - 行 1881: 内存写入日志
  - 行 1937, 1945, 1954: 对齐错误异常日志

- **Makefile**: 默认启用 `VERBOSE_DEBUG` 编译标志
  - 行 89: 添加 `-DVERBOSE_DEBUG` 到 Verilator 编译参数

### 其他文件

- **testbench_cli.cc**: CLI 测试台实现（新增 `+nohex` 自动注入逻辑）
- **testbench.v**: Testbench wrapper（新增 `+nohex` 可选跳过 hex 预加载）
- **.gitignore**: 更新忽略规则

## 日志格式

详细的日志格式说明见：`examples/skip_exception_standalone/DEBUG_LOG_FORMAT.md`

### 快速参考

```
REG_WRITE: x8  <= 0x12345678  (PC=0x70 INSN=0x67840413)
EXCEPTION: MISALIGNED_WORD ADDR=0x00000001 (PC=0x00000082 INSN=0x00092983)
TRAP: Entering trap state (PC=0x000000b8 INSN=0x00009002)
MEM_WRITE: ADDR=0x20000000 DATA=0x075bcd15 SIZE=4 (PC=0x000000ae INSN=0x00532023)
```

## 示例程序

### Skip Exception Standalone

位置：`examples/skip_exception_standalone/`

这是一个演示异常处理的独立程序，展示如何：
1. 处理非法指令异常
2. 处理内存对齐错误
3. 跳过故障指令继续执行

**运行：**
```bash
cd examples/skip_exception_standalone
make test-verbose          # 查看详细日志
make test                  # 正常运行
make test-vcd              # 生成波形文件
```

**文档：**
- `README.md`: 示例程序说明
- `DEBUG_LOG_FORMAT.md`: 详细的日志格式文档

## 使用建议

### 过滤特定日志

```bash
# 只看寄存器写入
make test-verbose | grep "REG_WRITE"

# 只看异常
make test-verbose | grep "EXCEPTION"

# 只看内存写入
make test-verbose | grep "MEM_WRITE"

# 追踪特定寄存器
make test-verbose | grep "REG_WRITE.*x10"
```

### 保存完整日志

```bash
./testbench_cli +verbose --timeout=10000 your_program.elf > debug.log 2>&1
```

### 关于固件加载

`testbench_cli` 会从 ELF 直接加载内存，并自动注入 `+nohex` 来跳过 `testbench.v` 里的 `$readmemh` 预加载，避免覆盖 ELF 内容。因此：
- 不需要再传 `+firmware=...`；
- 即使传了 `+firmware=...` 也会被忽略（以 ELF 为准）。

### 分析日志

```bash
# 统计异常次数
grep "EXCEPTION" debug.log | wc -l

# 查看异常类型分布
grep "EXCEPTION" debug.log | cut -d: -f2 | cut -d' ' -f2 | sort | uniq -c

# 查看最后的寄存器写入
grep "REG_WRITE" debug.log | tail -20
```

## 实现原理

### 编译时宏

使用 `VERBOSE_DEBUG` 宏在编译时决定是否包含调试代码：

```verilog
`ifdef VERBOSE_DEBUG
  `define verbose_debug(debug_command) debug_command
`else
  `define verbose_debug(debug_command)
`endif
```

### 零开销

未启用 `VERBOSE_DEBUG` 时，调试代码完全不会被编译，因此：
- ✅ 零运行时性能开销
- ✅ 零代码体积增加
- ✅ 可以在生产环境中使用未启用版本

## 性能考虑

- **日志输出量**: 详细日志会显著增加输出，建议使用过滤或重定向
- **仿真速度**: 大量 I/O 可能降低仿真速度，使用 `--timeout` 限制执行周期
- **文件大小**: 完整日志可能很大，考虑使用 `grep` 实时过滤

## 文档

- **本文件**: 项目概述和快速开始
- **VERBOSE_DEBUG_GUIDE.md**: 使用指南（根目录）
- **examples/skip_exception_standalone/DEBUG_LOG_FORMAT.md**: 详细日志格式说明

## 与原始 PicoRV32 的兼容性

本版本完全兼容原始 PicoRV32：
- ✅ 所有参数保持不变
- ✅ 接口完全相同
- ✅ 行为完全一致
- ✅ 可以关闭调试功能（移除 `-DVERBOSE_DEBUG`）

## 技术细节

### 日志层次

1. **高层日志（CPU 视角）**：
   - REG_WRITE: 寄存器写入，包含指令上下文
   - EXCEPTION: CPU 异常，包含异常原因
   - TRAP: CPU 陷阱状态
   - MEM_WRITE: 存储指令执行

2. **底层日志（总线视角）**：
   - RD: AXI 读事务
   - WR: AXI 写事务

### 信号来源

调试日志使用的信号：
- `dbg_insn_addr`: 当前指令地址
- `dbg_insn_opcode`: 当前指令编码
- `cpuregs_write`, `latched_rd`, `cpuregs_wrdata`: 寄存器写入信息
- `cpu_state`, `trap`: CPU 状态
- `mem_wordsize`, `reg_op1`, `reg_op2`: 内存访问信息

## 故障排除

### 没有调试输出？

检查：
1. 使用的是否是编译好的 `testbench_cli`？
2. 是否添加了 `+verbose` 参数？
3. 是否在 Makefile 中启用了 `-DVERBOSE_DEBUG`？

### 输出太多？

解决方案：
1. 使用 `grep` 过滤特定事件
2. 使用 `--timeout=N` 限制执行周期
3. 重定向到文件后分析

### 编译失败？

检查：
1. Verilator 是否正确安装？
2. 依赖的 C++ 编译器是否可用？
3. 查看具体错误信息

## 许可证

与原始 PicoRV32 相同的 ISC 许可证。

## 贡献者

基于 Claire Xenia Wolf 的 PicoRV32 项目。

调试功能增强：添加 VERBOSE_DEBUG 宏支持。
