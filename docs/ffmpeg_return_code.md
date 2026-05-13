# FFmpeg 退出码（Windows）

## 常见场景与返回值

| 结束方式 | 说明 | Windows 退出码（十进制） | Windows 退出码（十六进制） | Linux 退出码（十进制） |
|---|---|---:|---:|---:|
| `q` 正常退出 | 向 FFmpeg 标准输入发送 `q` | `0` | `0x00000000` | `0` |
| `CTRL+C` / `SIGINT` | 控制台中断事件 | `-1073741510` | `0xC000013A` | `255` |
| `CTRL+BREAK` / `SIGTERM` | 控制台中断事件（按进程组）/ 终止信号 | `255`（常见） | `0x000000FF` | `255` |
| `kill`（强制结束）/ `SIGKILL` | 直接终止进程（非优雅退出） | `1`（常见） | `0x00000001` | `137` |

> 说明：`kill`、`CTRL+BREAK`、`SIGTERM`、`SIGKILL` 的返回值可能受启动方式、封装层、子进程处理逻辑影响，实践中以实测为准。

Linux 实测输出（bash）：

- q_exit=0
- sigint_exit=255
- sigterm_exit=255
- ffmpeg_exit_linux_test.sh：行 33: 1835992 已杀死 ffmpeg -hide_banner -loglevel error -f lavfi -i testsrc2=s=128x128:r=25 -f null - > /dev/null 2>&1
- sigkill_exit=137

## 关于 `GenerateConsoleCtrlEvent` 的关键限制（微软官方）

根据微软官方文档（`GenerateConsoleCtrlEvent`）  
https://learn.microsoft.com/zh-cn/windows/console/generateconsolectrlevent


> CTRL_C_EVENT (0) 不能被限制到特定进程组。
> 如果 dwProcessGroupId 非零，函数会“成功返回”，
> 但指定组里的进程收不到 CTRL_C_EVENT。
> 只有 CTRL_BREAK_EVENT 才支持按进程组发送。


因此在“仅向某个进程组发送控制台信号”场景下，应优先使用 `CTRL_BREAK_EVENT`，不要依赖 `CTRL_C_EVENT`。

