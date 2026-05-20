"""最小可复现：communicate() 关闭 stdin 导致 ffmpeg 收不到 'q'。"""

import asyncio
import sys


async def bug_communicate():
    """旧写法：communicate() 立即关闭 stdin，'q' 无法送达。"""
    print("=== BUG: communicate() 关闭 stdin ===")

    proc = await asyncio.create_subprocess_exec(
        "ffmpeg",
        "-hide_banner",
        "-y",
        "-f",
        "lavfi",
        "-i",
        "testsrc2=s=1920x1080:r=30",
        "-t",
        "300",
        "-c:v",
        "libx264",
        "-preset",
        "slow",
        "-crf",
        "18",
        "bug_communicate.mp4",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )

    comm_task = asyncio.create_task(proc.communicate())

    # 等待 ffmpeg 开始编码
    await asyncio.sleep(1)

    # communicate() 已经关闭了 stdin
    print(f"  stdin.is_closing() = {proc.stdin.is_closing()}")

    if proc.returncode is not None:
        print("  ffmpeg 已退出，无法演示 bug（编码太快）")
        await comm_task
        return

    # 尝试发 q（会失败，因为管道已关闭）
    try:
        proc.stdin.write(b"q\n")
        await proc.stdin.drain()
        print("  写入 'q' 成功（不应该到这里）")
    except (BrokenPipeError, ConnectionResetError) as e:
        print(f"  写入 'q' 失败: {e!r}")

    proc.stdin.close()

    # ffmpeg 收不到 q，只能等它自己跑完或超时强杀
    print("  等待 ffmpeg 退出（10s 超时）...")
    try:
        await asyncio.wait_for(proc.wait(), timeout=10.0)
        print(f"  ffmpeg 在超时内退出, exit code = {proc.returncode}")
    except asyncio.TimeoutError:
        print("  超时！强制 kill")
        proc.kill()
        await proc.wait()
        print(f"  exit code = {proc.returncode}")
        print("  → 文件损坏：moov atom 未写入")

    await comm_task


async def fix_read_stderr():
    """修复写法：手动读 stderr，保持 stdin 打开，'q' 正常送达。"""
    print("\n=== FIX: 手动读 stderr，保持 stdin 打开 ===")

    proc = await asyncio.create_subprocess_exec(
        "ffmpeg",
        "-hide_banner",
        "-y",
        "-f",
        "lavfi",
        "-i",
        "testsrc2=s=1920x1080:r=30",
        "-t",
        "300",
        "-c:v",
        "libx264",
        "-preset",
        "slow",
        "-crf",
        "18",
        "fix_read_stderr.mp4",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )

    async def _read_stderr():
        chunks = []
        while True:
            chunk = await proc.stderr.read(4096)
            if not chunk:
                break
            chunks.append(chunk)
        return b"".join(chunks)

    stderr_task = asyncio.create_task(_read_stderr())

    # 等待 ffmpeg 开始编码
    await asyncio.sleep(1)

    # stdin 仍然打开
    print(f"  stdin.is_closing() = {proc.stdin.is_closing()}")

    if proc.returncode is not None:
        print("  ffmpeg 已退出，无法演示 fix（编码太快）")
        await stderr_task
        return

    # 发 q（成功送达）
    try:
        proc.stdin.write(b"q\n")
        await proc.stdin.drain()
        print("  写入 'q' 成功")
    except (BrokenPipeError, ConnectionResetError) as e:
        print(f"  写入 'q' 失败: {e!r}")
    proc.stdin.close()

    # 等待 ffmpeg 优雅退出
    print("  等待 ffmpeg 优雅退出（10s 超时）...")
    try:
        await asyncio.wait_for(proc.wait(), timeout=10.0)
        print(f"  ffmpeg 优雅退出, exit code = {proc.returncode}")
    except asyncio.TimeoutError:
        print("  超时！强制 kill")
        proc.kill()
        await proc.wait()
        print(f"  exit code = {proc.returncode}")

    await stderr_task


async def main():
    if len(sys.argv) < 2:
        print("用法: python scripts/reproduce_communicate_bug.py [bug|fix|both]")
        print("")
        print("  bug  — 演示 communicate() 关闭 stdin 导致 'q' 无法送达")
        print("  fix  — 演示手动读 stderr 保持 stdin 打开，'q' 正常送达")
        print("  both — 依次运行两个对比")
        return

    mode = sys.argv[1]

    if mode in ("bug", "both"):
        await bug_communicate()
    if mode in ("fix", "both"):
        await fix_read_stderr()


if __name__ == "__main__":
    asyncio.run(main())
