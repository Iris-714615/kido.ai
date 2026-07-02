"""image_generator 子 Agent：根据绘本配图 Prompt 生成绘本图片。

使用阿里云通义万相 wanx-v1 文生图模型（DashScope 异步任务模式）。

调用流程：
  1. POST 提交文生图任务 → 返回 task_id
  2. GET 轮询任务状态 → SUCCEEDED 时获取图片 URL
  3. 下载图片到本地存储

流式输出（async generator）：
  每张图片完成时 yield 一个进度事件，供 SSE 端点推送。
"""
from __future__ import annotations

import asyncio
import base64
import logging
import urllib.request
from dataclasses import dataclass
from typing import AsyncIterator

from app.core.settings import get_settings
from app.multi_agent import persistence
from app.multi_agent.schemas import ImagePromptItem, ImagePromptSet

logger = logging.getLogger(__name__)

# 通义万相 API 端点
_DASHSCOPE_T2I_URL = "https://dashscope.aliyuncs.com/api/v1/services/aigc/text2image/image-synthesis"
_DASHSCOPE_TASK_URL = "https://dashscope.aliyuncs.com/api/v1/tasks/{task_id}"

# 3-6 岁幼儿绘本：16:9 横版（通义万相允许值：1024*1024 / 720*1280 / 1280*720 / 768*1152）
DEFAULT_SIZE = "1280*720"
# 单张图片最大轮询次数（每次 3s 间隔，最长 ~90s）
MAX_POLL_ROUNDS = 30
POLL_INTERVAL_SEC = 3


@dataclass
class ImageGenEvent:
    """单张图片生成事件，用于流式推送。"""
    act: int
    status: str            # "pending" | "running" | "succeeded" | "failed"
    progress: int           # 0-100
    image_url: str | None = None   # 远端 URL（成功时）
    local_path: str | None = None  # 本地存储路径（成功时）
    error: str | None = None


def _api_key() -> str:
    """获取 DashScope API Key。"""
    settings = get_settings()
    key = settings.dashscope_api_key
    if not key:
        raise RuntimeError("DASHSCOPE_API_KEY 未配置，无法生成图片")
    return key


def _submit_task(prompt_en: str, negative_prompt: str) -> str:
    """提交文生图任务，返回 task_id。

    通义万相 wanx-v1 异步任务模式：Header X-DashScope-Async: enable。
    遇 429 限流自动退避重试（最多 4 次）。
    """
    import json
    import time as _time
    import urllib.error

    body = {
        "model": "wanx-v1",
        "input": {"prompt": prompt_en},
        "parameters": {
            "n": 1,
            "size": DEFAULT_SIZE,
            "negative_prompt": negative_prompt or "dark, scary, violent, realistic, photo",
        },
    }

    last_err = None
    for attempt in range(4):
        if attempt > 0:
            wait = min(10 * attempt, 30)
            _time.sleep(wait)
        req = urllib.request.Request(
            _DASHSCOPE_T2I_URL,
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {_api_key()}",
                "Content-Type": "application/json",
                "X-DashScope-Async": "enable",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                data = json.loads(r.read().decode("utf-8"))
            if data.get("code"):
                raise RuntimeError(f"通义万相提交失败：{data.get('code')} - {data.get('message')}")
            return data["output"]["task_id"]
        except urllib.error.HTTPError as e:
            last_err = e
            if e.code == 429:
                logger.warning("通义万相 429 限流，第 %s 次重试", attempt + 1)
                continue
            raise
    raise RuntimeError(f"通义万相任务提交失败（重试 4 次仍限流）: {last_err}")


def _poll_task(task_id: str) -> dict:
    """轮询任务状态，返回完整任务响应 JSON。"""
    import json

    req = urllib.request.Request(
        _DASHSCOPE_TASK_URL.format(task_id=task_id),
        headers={"Authorization": f"Bearer {_api_key()}"},
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode("utf-8"))


def _download_image(url: str, dest_path) -> str:
    """下载远端图片到本地，返回本地路径字符串。"""
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": "KidoAI/1.0"})
    with urllib.request.urlopen(req, timeout=60) as r, open(dest_path, "wb") as f:
        f.write(r.read())
    return str(dest_path)


async def generate_image_for_act(
    story_id: str,
    item: ImagePromptItem,
) -> tuple[ImageGenEvent, str | None]:
    """为单幕生成图片。

    Returns:
        (event, local_path) - event 用于流式推送，local_path 为本地存储路径（失败为 None）
    """
    story_dir = persistence._story_dir(story_id)
    images_dir = story_dir / "images"
    local_path = images_dir / f"act_{item.act}.png"

    # 已生成则跳过
    if local_path.exists():
        return (
            ImageGenEvent(
                act=item.act, status="succeeded", progress=100,
                local_path=str(local_path),
            ),
            str(local_path),
        )

    yield_placeholder = ImageGenEvent(act=item.act, status="running", progress=10)
    # 提交任务
    try:
        task_id = await asyncio.to_thread(_submit_task, item.prompt_en, item.negative_prompt)
    except Exception as e:
        logger.exception("通义万相任务提交失败 act=%s", item.act)
        return (
            ImageGenEvent(
                act=item.act, status="failed", progress=0,
                error=f"任务提交失败: {e}",
            ),
            None,
        )

    # 轮询
    for i in range(MAX_POLL_ROUNDS):
        await asyncio.sleep(POLL_INTERVAL_SEC)
        try:
            resp = await asyncio.to_thread(_poll_task, task_id)
        except Exception as e:
            logger.warning("轮询失败 act=%s round=%s: %s", item.act, i, e)
            continue

        status = resp.get("output", {}).get("task_status", "")
        if status == "SUCCEEDED":
            results = resp.get("output", {}).get("results", [])
            if not results:
                return (
                    ImageGenEvent(act=item.act, status="failed", progress=0,
                                  error="任务完成但无结果"),
                    None,
                )
            remote_url = results[0]["url"]
            # 下载到本地
            try:
                lp = await asyncio.to_thread(_download_image, remote_url, local_path)
            except Exception as e:
                logger.exception("图片下载失败 act=%s", item.act)
                return (
                    ImageGenEvent(
                        act=item.act, status="failed", progress=0,
                        image_url=remote_url,
                        error=f"下载失败: {e}",
                    ),
                    None,
                )
            return (
                ImageGenEvent(
                    act=item.act, status="succeeded", progress=100,
                    image_url=remote_url, local_path=lp,
                ),
                lp,
            )
        if status == "FAILED":
            err = resp.get("output", {}).get("message", "通义万相任务失败")
            return (
                ImageGenEvent(act=item.act, status="failed", progress=0, error=err),
                None,
            )
        # 仍在 PENDING / RUNNING

    return (
        ImageGenEvent(act=item.act, status="failed", progress=0,
                      error="轮询超时（>90s）"),
        None,
    )


async def stream_generate_images(
    story_id: str,
    image_set: ImagePromptSet,
) -> AsyncIterator[dict]:
    """流式生成所有幕图片，按完成顺序 yield SSE 友好事件。

    串行执行（避免通义万相并发限流 429），每张完成立即推送。
    """
    items = image_set.prompts
    total = len(items)
    if total == 0:
        yield {"type": "complete", "total": 0, "succeeded": 0, "failed": 0}
        return

    # 全部开始
    yield {
        "type": "start", "total": total, "story_id": story_id,
        "acts": [{"act": it.act, "scene_cn": it.scene_cn} for it in items],
    }

    succeeded = 0
    failed = 0
    finished = 0
    images_manifest = []

    # 串行执行（避免通义万相 API 限流 429）
    for item in items:
        event, local_path = await generate_image_for_act(story_id, item)
        finished += 1
        if event.status == "succeeded":
            succeeded += 1
        else:
            failed += 1

        yield {
            "type": "image_done",
            "act": event.act,
            "status": event.status,
            "progress": event.progress,
            "image_url": event.image_url,
            "local_path": event.local_path,
            "error": event.error,
            "finished": finished,
            "total": total,
        }
        images_manifest.append({
            "act": item.act,
            "scene_cn": item.scene_cn,
            "prompt_en": item.prompt_en,
            "image_url": event.image_url,
            "local_path": event.local_path,
            "status": event.status,
            "error": event.error,
        })

    # 保存图片清单 manifest
    manifest = {
        "story_id": story_id,
        "total": total,
        "succeeded": succeeded,
        "failed": failed,
        "images": images_manifest,
    }
    persistence.save_image_manifest(story_id, manifest)

    yield {
        "type": "complete",
        "total": total,
        "succeeded": succeeded,
        "failed": failed,
    }
