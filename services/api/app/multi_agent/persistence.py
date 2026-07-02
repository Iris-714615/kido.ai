"""故事持久化（文件存储，等价 deepagents StoreBackend）。

存储布局：
  {storage_dir}/stories/{story_id}/
      story.md        完整故事正文
      prompts.json    各幕配图 Prompt
      safety.json     安全审核报告
      metadata.json   绘本元数据
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.core.settings import get_settings
from app.multi_agent.schemas import StoryMetadata


def _stories_root() -> Path:
    root = get_settings().storage_dir / "stories"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _story_dir(story_id: str) -> Path:
    d = _stories_root() / story_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def _write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def save_story_text(story_id: str, text: str) -> Path:
    path = _story_dir(story_id) / "story.md"
    path.write_text(text, encoding="utf-8")
    return path


def save_image_prompts(story_id: str, prompts: dict) -> Path:
    path = _story_dir(story_id) / "prompts.json"
    _write_json(path, prompts)
    return path


def save_safety_report(story_id: str, report: dict) -> Path:
    path = _story_dir(story_id) / "safety.json"
    _write_json(path, report)
    return path


def save_metadata(meta: StoryMetadata) -> Path:
    path = _story_dir(meta.story_id) / "metadata.json"
    _write_json(path, meta.model_dump(mode="json"))
    return path


def load_metadata(story_id: str) -> StoryMetadata | None:
    path = _story_dir(story_id) / "metadata.json"
    if not path.exists():
        return None
    return StoryMetadata(**json.loads(path.read_text(encoding="utf-8")))


def load_story_text(story_id: str) -> str | None:
    path = _story_dir(story_id) / "story.md"
    return path.read_text(encoding="utf-8") if path.exists() else None


def load_safety_report(story_id: str) -> dict | None:
    path = _story_dir(story_id) / "safety.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def load_image_prompts(story_id: str) -> dict | None:
    path = _story_dir(story_id) / "prompts.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


# ── 图片生成结果 ──────────────────────────────────────────
def save_image_manifest(story_id: str, manifest: dict) -> Path:
    """保存图片生成清单（manifest.json）。"""
    path = _story_dir(story_id) / "manifest.json"
    _write_json(path, manifest)
    # 同步更新 metadata 的 image_count 与封面
    meta = load_metadata(story_id)
    if meta:
        meta.image_count = manifest.get("succeeded", 0)
        # 取首张成功图片作为封面
        for it in manifest.get("images", []):
            if it.get("status") == "succeeded" and it.get("local_path"):
                meta.cover_image_path = it["local_path"]
                break
        save_metadata(meta)
    return path


def load_image_manifest(story_id: str) -> dict | None:
    path = _story_dir(story_id) / "manifest.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def get_image_path(story_id: str, act: int) -> Path | None:
    """获取指定幕的本地图片路径。"""
    p = _story_dir(story_id) / "images" / f"act_{act}.png"
    return p if p.exists() else None


def list_all_stories() -> list[dict]:
    """列出所有绘本目录（按更新时间倒序）。

    用于「我的绘本集」列表。
    """
    root = _stories_root()
    items = []
    for d in root.iterdir():
        if not d.is_dir():
            continue
        meta_path = d / "metadata.json"
        if not meta_path.exists():
            continue
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            items.append(meta)
        except Exception:  # noqa: BLE001
            continue
    # 按 updated_at 倒序
    items.sort(key=lambda x: x.get("updated_at", ""), reverse=True)
    return items
