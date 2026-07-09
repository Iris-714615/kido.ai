"""多智能体 FastAPI 路由（对应设计规范第六章）。

独立挂载，prefix=/stories，与现有 deep_router 物理隔离。
"""
from __future__ import annotations

import asyncio
import json
import logging
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from app.dependencies import get_current_child_profile
from app.models import ChildProfile
from app.multi_agent import persistence
from app.multi_agent.pipeline import get_pipeline
from app.multi_agent.schemas import (
    HumanReviewDecision,
    StoryCreationRequest,
    StoryCreationResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/stories", tags=["multi-agent-story"])

# 后台任务引用集合：保存 asyncio.create_task 返回的引用，
# 防止任务被 GC 中途回收（Python 官方文档推荐做法）。
_background_tasks: set[asyncio.Task] = set()


def _spawn_background_task(coro) -> asyncio.Task:
    """创建后台任务并保存引用，完成后自动从集合移除。"""
    task = asyncio.create_task(coro)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return task


def _child_id(child: ChildProfile) -> str:
    return str(child.id)


def _check_story_owner(story_id: str, child: ChildProfile) -> None:
    """校验绘本归属权，防止 IDOR 越权访问他人绘本。

    - 优先从 metadata.child_id 校验
    - 若 metadata 不存在（流水线早期），从 pipeline state 的 request.child_id 校验
    - 若两者都不存在，抛 404
    - 若 child_id 为 None（旧数据/系统数据），允许访问
    - 若 child_id 存在且不匹配，抛 403
    """
    meta = persistence.load_metadata(story_id)
    owner = meta.child_id if meta else None

    if owner is None and not meta:
        # metadata 尚未创建，尝试从 pipeline state 读取归属权
        try:
            pipeline = get_pipeline()
            state = pipeline.get_state({"configurable": {"thread_id": story_id}})
            if state and state.values:
                req = state.values.get("request") or {}
                owner = req.get("child_id")
        except Exception:  # noqa: BLE001
            pass

    if owner is None and not meta:
        # 既无 metadata 也无 state，绘本不存在
        raise HTTPException(status_code=404, detail="故事不存在")

    if owner is not None and owner != _child_id(child):
        logger.warning(
            "IDOR 拦截: child=%s 试图访问 story_id=%s (owner=%s)",
            _child_id(child), story_id, owner,
        )
        raise HTTPException(status_code=403, detail="无权访问该绘本")


# ── 后台执行流水线 ────────────────────────────────────────
async def _run_pipeline_async(story_id: str, request: StoryCreationRequest):
    pipeline = get_pipeline()
    config = {"configurable": {"thread_id": story_id}}
    try:
        await pipeline.ainvoke(
            {
                "story_id": story_id,
                "request": request.model_dump(),
                "pipeline_stage": "init",
                "revision_count": 0,
                "messages": [{
                    "role": "user",
                    "content": (
                        f"请帮我创作一个故事：{request.story_prompt}，"
                        f"目标年龄{request.target_age}岁，主题偏好{request.preferred_theme}"
                    ),
                }],
            },
            config=config,
        )
    except Exception:  # noqa: BLE001
        logger.exception("故事流水线执行失败 story_id=%s", story_id)
        meta = persistence.load_metadata(story_id)
        if meta:
            meta.status = "failed"
            persistence.save_metadata(meta)


# ── 接口 ──────────────────────────────────────────────────
@router.post("/create", response_model=StoryCreationResponse)
async def create_story(
    request: StoryCreationRequest,
    child: ChildProfile = Depends(get_current_child_profile),
):
    """孩子发起绘本创作，立即返回 story_id，后台异步执行完整流水线。"""
    request.child_id = _child_id(child)
    story_id = f"story_{uuid4().hex[:8]}"
    _spawn_background_task(_run_pipeline_async(story_id, request))
    return StoryCreationResponse(
        story_id=story_id,
        status="creating",
        message="正在为你创作绘本，大约需要 3 分钟 ✨",
        eta_seconds=180,
    )


@router.get("/{story_id}/status")
async def get_status(
    story_id: str,
    child: ChildProfile = Depends(get_current_child_profile),
):
    """轮询当前流水线阶段与安全分数。"""
    _check_story_owner(story_id, child)
    pipeline = get_pipeline()
    config = {"configurable": {"thread_id": story_id}}
    state = pipeline.get_state(config)
    meta = persistence.load_metadata(story_id)
    if not state and not meta:
        raise HTTPException(status_code=404, detail="故事不存在")

    values = state.values if state else {}
    report = values.get("safety_report") or (meta.model_dump(mode="json") if meta else {})
    stage = values.get("pipeline_stage") or (meta.status if meta else "unknown")
    pending_review = bool(state and state.next and "human_review" in state.next)

    return {
        "story_id": story_id,
        "stage": stage,
        "safety_score": report.get("safety_score") or report.get("overall_score"),
        "risk_level": report.get("risk_level"),
        "pending_review": pending_review,
        "revision_count": values.get("revision_count", meta.revision_count if meta else 0),
        "title": meta.title if meta else None,
    }


@router.post("/{story_id}/review")
async def submit_review(
    story_id: str,
    decision: HumanReviewDecision,
    child: ChildProfile = Depends(get_current_child_profile),
):
    """家长/运营提交人工审核结果，恢复被 interrupt_before 暂停的流水线。"""
    _check_story_owner(story_id, child)
    pipeline = get_pipeline()
    config = {"configurable": {"thread_id": story_id}}
    state = pipeline.get_state(config)
    if not state or not state.next or "human_review" not in state.next:
        raise HTTPException(status_code=400, detail="该绘本当前不在待审核状态")

    if decision.action == "revise" and not decision.comment:
        raise HTTPException(status_code=400, detail="revise 时需提供修改建议")

    await pipeline.aupdate_state(config, {
        "reviewer_decision": decision.action,
        "reviewer_comment": decision.comment or "",
    })
    _spawn_background_task(pipeline.ainvoke(None, config=config))

    action_msg = {"approve": "已批准发布", "revise": "已提交修改意见", "reject": "已拒绝"}
    return {"story_id": story_id, "message": action_msg.get(decision.action, "已处理")}


@router.get("/{story_id}/result")
async def get_result(
    story_id: str,
    child: ChildProfile = Depends(get_current_child_profile),
):
    """获取最终绘本内容（故事正文 + 配图 + 安全报告）。"""
    _check_story_owner(story_id, child)
    meta = persistence.load_metadata(story_id)
    if not meta:
        raise HTTPException(status_code=404, detail="故事不存在")
    return {
        "story_id": story_id,
        "metadata": meta.model_dump(mode="json"),
        "story_text": persistence.load_story_text(story_id),
        "image_prompts": persistence.load_image_prompts(story_id),
        "safety_report": persistence.load_safety_report(story_id),
    }


@router.get("/{story_id}/stream")
async def stream_progress(
    story_id: str,
    child: ChildProfile = Depends(get_current_child_profile),
):
    """SSE 流式推送创作进度。"""
    _check_story_owner(story_id, child)
    stage_labels = {
        "plan_story": "✍️ 正在规划故事大纲...",
        "planning_done": "✍️ 故事骨架已规划",
        "launch_creation": "🚀 故事创作已启动！",
        "creation_done": "✨ 故事正文与配图已生成",
        "run_safety_check": "🔍 内容安全检查中...",
        "safety_checking": "🔍 安全审核完成",
        "human_review": "⏳ 等待叔叔阿姨确认...",
        "reviewed": "✅ 人工审核已处理",
        "revise_story": "✏️ 正在优化内容...",
        "revising": "✏️ 内容已修订",
        "publish_story": "🎉 绘本创作完成！",
        "published": "🎉 绘本已发布",
        "reject_story": "❌ 很抱歉，内容需要调整",
        "rejected": "❌ 绘本已被拒绝",
    }

    async def generator():
        pipeline = get_pipeline()
        config = {"configurable": {"thread_id": story_id}}
        last_stage = None
        for _ in range(120):  # 最多轮询 10 分钟
            state = pipeline.get_state(config)
            if state is None:
                yield f"data: {json.dumps({'type': 'error', 'message': '故事不存在'})}\n\n"
                return
            stage = state.values.get("pipeline_stage", "init")
            if stage != last_stage:
                label = stage_labels.get(stage, stage)
                yield f"data: {json.dumps({'type': 'progress', 'stage': stage, 'label': label})}\n\n"
                last_stage = stage
            if state.next:
                if "human_review" in state.next:
                    yield f"data: {json.dumps({'type': 'pending_review', 'stage': stage})}\n\n"
                    return
                await asyncio.sleep(5)
            else:
                final = "published" if stage in ("publish_story", "published") else "rejected"
                yield f"data: {json.dumps({'type': 'complete', 'story_id': story_id, 'result': final})}\n\n"
                yield "data: [DONE]\n\n"
                return

    return StreamingResponse(generator(), media_type="text/event-stream")


# ── 图片生成（image_generator agent） ─────────────────────
@router.post("/{story_id}/images/generate")
async def generate_images(
    story_id: str,
    child: ChildProfile = Depends(get_current_child_profile),
):
    """触发图片生成 agent，为每幕生成绘本图片。

    立即返回起始事件，前端应转而订阅 SSE 流获取进度。
    """
    _check_story_owner(story_id, child)
    meta = persistence.load_metadata(story_id)
    if not meta:
        raise HTTPException(status_code=404, detail="故事不存在")
    if meta.status != "published":
        raise HTTPException(status_code=400, detail=f"故事尚未发布，当前状态: {meta.status}")

    prompts_data = persistence.load_image_prompts(story_id)
    if not prompts_data:
        raise HTTPException(status_code=400, detail="未找到配图 Prompt，无法生成图片")

    from app.multi_agent.schemas import ImagePromptSet
    image_set = ImagePromptSet(**prompts_data)

    # 已存在 manifest 视为已完成
    existing = persistence.load_image_manifest(story_id)
    if existing and existing.get("succeeded", 0) > 0:
        return {
            "story_id": story_id,
            "status": "already_done",
            "total": existing.get("total"),
            "succeeded": existing.get("succeeded"),
            "message": "绘本图片已生成，可直接查看",
        }

    # 后台异步生成（不阻塞响应）
    _spawn_background_task(_run_image_generation(story_id, image_set))
    return {
        "story_id": story_id,
        "status": "started",
        "total": len(image_set.prompts),
        "message": "图片生成已启动，请订阅 SSE 流获取进度",
    }


async def _run_image_generation(story_id: str, image_set):
    """后台执行图片生成（结果持久化在 manifest 中）。"""
    from app.multi_agent import image_generator
    try:
        async for _event in image_generator.stream_generate_images(story_id, image_set):
            # 后台执行不需要推送，仅推进生成
            pass
    except Exception:  # noqa: BLE001
        logger.exception("图片生成失败 story_id=%s", story_id)


@router.get("/{story_id}/images/stream")
async def stream_image_progress(
    story_id: str,
    child: ChildProfile = Depends(get_current_child_profile),
):
    """SSE 流式推送图片生成进度。

    每张图片完成时推送一条事件，全部完成后推送 [DONE]。
    若图片已生成完毕，立即推送 complete 事件。
    """
    _check_story_owner(story_id, child)
    meta = persistence.load_metadata(story_id)
    if not meta:
        raise HTTPException(status_code=404, detail="故事不存在")

    prompts_data = persistence.load_image_prompts(story_id)
    if not prompts_data:
        raise HTTPException(status_code=400, detail="未找到配图 Prompt")

    from app.multi_agent.schemas import ImagePromptSet
    image_set = ImagePromptSet(**prompts_data)

    async def generator():
        from app.multi_agent import image_generator
        try:
            async for event in image_generator.stream_generate_images(story_id, image_set):
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        except Exception as e:  # noqa: BLE001
            logger.exception("图片生成流异常 story_id=%s", story_id)
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(generator(), media_type="text/event-stream")


@router.get("/{story_id}/images")
async def get_images(
    story_id: str,
    child: ChildProfile = Depends(get_current_child_profile),
):
    """获取绘本所有图片清单（含本地路径与状态）。"""
    _check_story_owner(story_id, child)
    meta = persistence.load_metadata(story_id)
    if not meta:
        raise HTTPException(status_code=404, detail="故事不存在")
    manifest = persistence.load_image_manifest(story_id)
    if not manifest:
        raise HTTPException(status_code=404, detail="图片尚未生成")
    return {
        "story_id": story_id,
        "title": meta.title,
        "total": manifest.get("total", 0),
        "succeeded": manifest.get("succeeded", 0),
        "failed": manifest.get("failed", 0),
        "images": manifest.get("images", []),
    }


@router.get("/{story_id}/images/{act}/file")
async def get_image_file(
    story_id: str,
    act: int,
    child: ChildProfile = Depends(get_current_child_profile),
):
    """获取指定幕的图片文件（直接返回 png）。"""
    _check_story_owner(story_id, child)
    from fastapi.responses import FileResponse
    path = persistence.get_image_path(story_id, act)
    if not path:
        raise HTTPException(status_code=404, detail=f"第 {act} 幕图片不存在")
    return FileResponse(path, media_type="image/png")


# ── 我的绘本集 ────────────────────────────────────────────
@router.get("")
async def list_storybooks(
    child: ChildProfile = Depends(get_current_child_profile),
):
    """「我的绘本集」列表：当前孩子拥有的已发布绘本。

    返回字段：story_id、title、target_age、safety_score、risk_level、
    cover_image_path、image_count、created_at、updated_at。
    """
    # 仅返回当前孩子拥有的绘本，防止越权列出他人绘本
    items = persistence.list_stories_by_child(_child_id(child))
    # 仅返回已发布 + 已生成图片的
    published = [
        it for it in items
        if it.get("status") == "published"
    ]
    return {
        "total": len(published),
        "items": published,
    }


@router.get("/{story_id}/package")
async def package_storybook(
    story_id: str,
    child: ChildProfile = Depends(get_current_child_profile),
):
    """打包绘本为 zip 下载（含正文 + 图片 + manifest）。"""
    _check_story_owner(story_id, child)
    import io
    import zipfile
    from fastapi.responses import StreamingResponse as _SS

    meta = persistence.load_metadata(story_id)
    if not meta:
        raise HTTPException(status_code=404, detail="故事不存在")

    story_text = persistence.load_story_text(story_id) or ""
    manifest = persistence.load_image_manifest(story_id) or {}

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        # 元数据
        zf.writestr("metadata.json", json.dumps(meta.model_dump(mode="json"), ensure_ascii=False, indent=2))
        # 故事正文
        zf.writestr("story.md", story_text)
        # 配图 Prompt
        prompts = persistence.load_image_prompts(story_id)
        if prompts:
            zf.writestr("prompts.json", json.dumps(prompts, ensure_ascii=False, indent=2))
        # 图片清单
        if manifest:
            zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        # 所有图片
        for it in manifest.get("images", []):
            if it.get("local_path"):
                from pathlib import Path
                p = Path(it["local_path"])
                if p.exists():
                    zf.write(p, f"images/act_{it['act']}.png")
    buf.seek(0)

    filename = f"storybook_{story_id}.zip"
    return _SS(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
