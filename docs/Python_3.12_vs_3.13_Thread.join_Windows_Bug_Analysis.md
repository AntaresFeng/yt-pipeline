# Python 3.12 vs 3.13 Windows Thread.join() 伪返回 Bug 分析

## 概述

在 Windows 上，Python ≤ 3.12 版本中，如果在 `Ctrl+C` 后调用 `Thread.join()`，该方法会**伪返回**（spurious return）——即使 worker 线程仍在运行，`join()` 也会立刻返回，导致主线程错误地认为 worker 已停止。

Python 3.13.0 通过完全重写 Thread 同步机制修复了这一问题。

---

## 问题表现

### 脚本行为（3.12 及以前，Windows）

```python
# MRE/1.py
# ... worker 线程做 CPU 密集工作，stop_event 永不 set（理论上永不退出）

try:
    while t.is_alive():
        t.join(0.1)  # 循环轮询
except KeyboardInterrupt:
    print("[main] 捕获 Ctrl+C, pass")
    pass

t.join()  # <-- BUG: 立刻返回，尽管 worker 仍在跑
print("[main] 结束")
if t.is_alive():  # <-- True! worker 仍活着
    print("[main] Warning: worker 线程未按时结束")
if not down_event.is_set():  # <-- True! worker 未正确退出
    print("[main] Warning: worker 线程未正确设置 down_event")
```

**实际输出（3.12）**：
```
[worker-python] 运行中...
[worker-python] 运行中...
...
[main] 捕获 Ctrl+C, pass
[main] 结束
[worker-python] 运行中...  <-- 线程仍在运行！
[main] Warning: worker 线程未按时结束
[main] Warning: worker 线程未正确设置 down_event
```

**预期行为（3.13.0）**：
- 脚本无限期挂起于第 36 行 `t.join()`
- 因为 `stop_event` 永不 set，worker 永不退出，join 正确地永久等待

---

## 根本原因

### 3.12 及以前的实现：`_tstate_lock` 机制

#### 核心设计

Python 的 `Thread.join()` 依赖 `Thread._tstate_lock`——一个由 worker 线程的 `PyThreadState` 对象管理的内部锁：

```python
# Lib/threading.py (3.12 之前的简化版本)
def _wait_for_tstate_lock(self, block=True, timeout=-1):
    lock = self._tstate_lock  # worker 线程 teardown 时由运行时释放的锁
    if lock is None:
        assert self._is_stopped
        return
    
    # 主线程阻塞在此，直到 worker 释放 _tstate_lock
    if lock.acquire(block, timeout):
        lock.release()
        self._stop()
```

**关键事实**：
- `_tstate_lock` **由 worker 线程自己持有**，仅在 PyThreadState 被摧毁时（线程正常退出）由运行时释放
- 主线程在 `join()` 中的作用是**等待** worker 释放该锁，而非试图自己获得它

#### 伪返回的 Bug 路径

当 `Ctrl+C` 被按下，主线程的 `lock.acquire()` 被 `KeyboardInterrupt` 中断：

```python
def _wait_for_tstate_lock(self, block=True, timeout=-1):
    lock = self._tstate_lock
    if lock is None:
        assert self._is_stopped
    elif lock.acquire(block, timeout):
        lock.release()
        self._stop()
    # <-- KeyboardInterrupt 可能在上面任何地方抛出
```

历史实现在外层（或内层）有一个 `except` 子句：

```python
try:
    if lock.acquire(block, timeout):
        lock.release()
        self._stop()
except BaseException:  # 包括 KeyboardInterrupt
    if lock.locked():
        lock.release()  # <-- 这里是 BUG！
    raise
```

**问题**：
这个 `except` 块假设"如果异常抛出且锁仍被锁定，则当前线程（主线程）持有它"。但这个假设**完全错误**：
- `_tstate_lock` 始终由 **worker 线程** 持有
- 主线程在此 **等待 worker 释放它**，从未试图 acquire

**后果**：
1. `KeyboardInterrupt` → except 块执行
2. `lock.locked()` 返回 True（worker 仍持有）
3. `lock.release()` **把本不属于主线程的锁释放掉**
4. 主线程回到 join 循环，再次调用 `_wait_for_tstate_lock()`
5. `lock.acquire()` **立刻成功**（锁已被主线程自己刚才释放）
6. `self._stop()` 被调用，Thread 标记为已停
7. 主线程返回 `join()`
8. **但 OS worker 线程仍在运行**

这就解释了为什么 `t.is_alive()` 返回 True、`down_event` 永不被 set。

#### 为什么是 Windows 特定

在 3.12 及以前，Windows 的条件变量实现（`SleepConditionVariableSRW`）和信号处理交互存在特殊问题，使得 `lock.acquire()` 更容易在这种半破坏状态下返回成功。POSIX 系统虽然也有类似问题，但表现形式不同。

---

## 历史修复尝试

### 2021 年：gh-89437 / bpo-45274

[**Race condition in Thread._wait_for_tstate_lock()**](https://github.com/python/cpython/issues/89437)

这个 issue 修复了 `_tstate_lock` 机制中的**另一个竞争**：worker 释放锁与调用 `_stop()` 之间的窗口。但根本的 `_tstate_lock` 设计本身没变，"伪返回"这种 bug 仍然存在。

---

## 3.13.0 的真正修复：PR #114839

### 彻底重写同步机制

[**gh-114271: Make `_threadmodule.c` thread-safe**](https://github.com/python/cpython/issues/114271)  
[**PR #114839: Fix race in `Thread.join()`**](https://github.com/python/cpython/pull/114839)  
合并时间：**2024-03-16**  
Commit: [`33da0e8`](https://github.com/python/cpython/commit/33da0e8)  
版本：**Python 3.13**

### 核心改动

**移除 `_tstate_lock`，改用 `PyThreadState` 上的 event**：

- 不再依赖 Python 代码中容易出 bug 的 `lock.acquire()` 循环
- 改为由 **CPython 运行时** 在线程清理时直接 set 一个 event
- `Thread.join()` 等待这个 event，语义更清晰，没有"我在 acquire 什么"的混淆

### 为什么这彻底解决问题

1. `_tstate_lock` 消失 → `_wait_for_tstate_lock()` 整段代码消失或重写
2. 伪返回的 `except: lock.release()` 路径 → **不复存在**
3. 没有错误释放别人的锁的机会

### 未回填 3.12

该 PR 的改动太大（涉及 C API 和内部 PyThreadState 结构），**不向后兼容**。所以 3.12.x 系列整个都留着旧代码和 bug。

---

## 相关但不同的问题（易混淆）

| 问题 | 说什么 | 根因 | 何时修 | 状态 |
|------|--------|------|--------|------|
| [gh-89437](https://github.com/python/cpython/issues/89437) (bpo-45274) | `_tstate_lock` 的竞争窗口 | worker release vs _stop() | 2021 | 修过，但基础机制还在 |
| [gh-66021](https://github.com/python/cpython/issues/66021) (bpo-21822) | Windows 上 join 伪返回 + hang | 上面的伪返回 + except 错误 | 2024 (PR#114839) | **用户这个 bug**：随 #114839 修 |
| [gh-74157](https://github.com/python/cpython/issues/74157) (bpo-29971) | `Lock.acquire()` Windows 不响应 Ctrl+C | Windows condvar 不能被信号唤醒 | **3.14** (PR #125546) | 未修（3.13） |
| [gh-139689](https://github.com/python/cpython/issues/139689) | join 不能被 Ctrl+C **中断** | 和上面类似，但针对 join | 开票者说 3.13 仍有 | **未修** |

**要点**：gh-74157 和 gh-139689 说的是"Ctrl+C 无法中断 join"（join 无限期阻塞）。用户遇到的是相反的问题："Ctrl+C 中断后 join 伪返回"。这两个问题都和 Windows condvar 有关，但根源和修复路径不同。

---

## 时间线

| 时间 | 事件 |
|------|------|
| 2014-06-21 | bpo-21822 首次报告 Windows join 问题 |
| 2017-08 | python-dev 讨论 Windows Ctrl+C interrupt 问题 |
| 2021-09-27 | bpo-45274 (gh-89437) 修复 _tstate_lock 竞争 |
| 2023-11 | gh-110829: 确保 Thread.join 等 OS thread |
| 2024-03-16 | **gh-114271 PR #114839** 删除 `_tstate_lock`，改用 event |
| 2024 | **Python 3.13.0 发布**，问题消失 |
| 2024-11+ | gh-125541 / PR #125546（3.14 新增）修复 `Lock.acquire()` 在 Windows 上不可被 Ctrl+C 中断 |
| 2025-10 | gh-139689 报告 join 仍不可被 Ctrl+C 中断（仍未修） |

---

## 原始资料

### 关键讨论

- **[discuss.python.org — KeyboardInterrupt behavior with multiple threads](https://discuss.python.org/t/keyboardinterrupt-behavior-with-multiple-threads/30756/5)** (eryksun) 
  - 逐句解释为何 `except: lock.release()` 假设错误
  - 说明 `_tstate_lock` 始终由 worker 持有

- **[Victor Stinner — Threading shutdown race condition](https://vstinner.github.io/threading-shutdown-race-condition.html)**
  - 解释 `_tstate_lock` 为何存在
  - 为何 `Thread.join()` 需要等待 worker 清理

### CPython Issues

- [gh-114271](https://github.com/python/cpython/issues/114271) — 总览 issue
- [gh-114839](https://github.com/python/cpython/pull/114839) — 修复 PR
- [gh-89437](https://github.com/python/cpython/issues/89437) — 早期竞争修复
- [gh-66021](https://github.com/python/cpython/issues/66021) — 原始 Windows 报告
- [gh-139689](https://github.com/python/cpython/issues/139689) — 仍未修的另一个问题

### 官方文档

- [Python 3.13 — What's New](https://docs.python.org/3.13/whatsnew/3.13.html) — 查看 threading 改动
- [Python 3.14 — threading 模块文档](https://docs.python.org/3/library/threading.html) — 记录 3.14 Lock.acquire() 改动

---

## 总结

**一句话**：Python ≤ 3.12 Windows 上，`Thread._wait_for_tstate_lock()` 在处理 `Ctrl+C` 异常时会错误地释放 worker 线程持有的 `_tstate_lock`，导致下次 `acquire()` 立刻成功、`join()` 伪返回——主线程认为 worker 停了但它仍在跑。Python 3.13 的 [PR #114839](https://github.com/python/cpython/pull/114839) 彻底删除了 `_tstate_lock` 设计，改用运行时 event 同步，根本消除了伪返回的可能性。

**修复版本**：3.13.0 及更新  
**受影响版本**：3.12 及以前  
**平台**：Windows（POSIX 虽有类似问题但表现不同）

---

## 兼容 3.12 及以下版本的规避方案

### 核心原则

**不能信任以下两个 API 的返回值来判断 worker"真正"退出了**：
- `t.join()` 返回 ≠ worker 已停止（可能伪返回）
- `t.is_alive()` 返回 `False` ≠ worker 已停止（`_stop()` 被错误调用后 `is_alive()` 就变 False 了）

**唯一可信的权威信号**：由 worker 线程自己 set 的 `threading.Event`。

---

### 规避方案

#### 1. `down_event` 作为唯一退出确认 + 带超时的轮询 join

```python
def safe_join(t: threading.Thread, down_event: threading.Event) -> None:
    """替代 t.join()，兼容 3.12 及以下版本的 _tstate_lock 伪返回"""
    while not down_event.wait(timeout=0.5):
        pass  # down_event 未 set 就继续等，忽略 t.is_alive()
```

这完全绕开 `_tstate_lock` 路径，只看 worker 自己的信号。

---

#### 2. `KeyboardInterrupt` 后立即 set `stop_event`，再等

```python
stop_event = threading.Event()
down_event = threading.Event()

try:
    while t.is_alive():
        t.join(0.1)
except KeyboardInterrupt:
    stop_event.set()  # 先通知 worker，给它正常退出的机会

# 不信任 t.join()，改用 down_event 轮询
safe_join(t, down_event)
print("[main] worker 已确认退出")
```

**关键**：Ctrl+C 后必须先 `stop_event.set()`，否则 worker 永远不会退出，`down_event` 永远不会 set。

---

#### 3. Worker 自身确保 `down_event.set()` 走 `finally`

```python
def worker(stop_event: threading.Event) -> None:
    try:
        while not stop_event.is_set():
            heavy_computation()
        print("[worker] 正常退出")
    except BaseException:
        print("[worker] 异常退出")
        raise
    finally:
        down_event.set()  # 无论正常/异常/KeyboardInterrupt，都要 set
```

`finally` 保证 `down_event` 一定会被 set，哪怕 worker 里也有异常。

---

### 修复后的完整脚本

```python
import threading


down_event = threading.Event()
stop_event = threading.Event()


def heavy_computation():
    x = 0
    for i in range(1000000):
        x += i * i
    return x


def worker(stop_event: threading.Event) -> None:
    try:
        while not stop_event.is_set():
            print("[worker] 运行中...")
            heavy_computation()
        print("[worker] 收到停止信号，退出")
    finally:
        down_event.set()  # 无论如何都 set


def safe_join(t: threading.Thread, done: threading.Event) -> None:
    while not done.wait(timeout=0.5):
        pass


t = threading.Thread(target=worker, args=(stop_event,))
t.start()

try:
    while t.is_alive():
        t.join(0.1)
except KeyboardInterrupt:
    print("\n[main] 捕获 Ctrl+C，通知 worker 停止")
    stop_event.set()

safe_join(t, down_event)  # 替代 t.join()
print("[main] 结束（worker 已确认退出）")
```

---

### 注意事项速查

| 情况 | ≤ 3.12 Windows 是否安全 | 说明 |
|---|---|---|
| `t.join()` 后信任 `t.is_alive()` | ❌ | 伪返回后 `is_alive()` 已被错误置 False |
| `t.join(timeout)` 轮询 | ⚠️ | join 本身可能伪返回，不能作为唯一判据 |
| `down_event.wait(timeout=...)` 轮询 | ✅ | 走 Event 路径，不依赖 `_tstate_lock` |
| worker 用 `finally: down_event.set()` | ✅ | 唯一可信的退出信号 |
| Ctrl+C 后先 `stop_event.set()` | ✅ | 给 worker 正常退出的机会 |
| 3.12 Windows 上 `Event.wait()` 不可被 Ctrl+C 中断 | ⚠️ | 必须带 `timeout`，否则 main 在等 Event 时自己也会卡住 |

最后一条要注意：在 3.12 及以前，`down_event.wait()` **不带超时的版本** 在 Windows 上同样不能被 Ctrl+C 中断（[bpo-35935](https://bugs.python.org/issue35935)），所以务必写 `wait(timeout=N)` 而不是 `wait()`。
