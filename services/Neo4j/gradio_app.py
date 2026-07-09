# -*- coding: utf-8 -*-
"""KidoAI 知识图谱查询智能体 - gradio_app.py

提供：
1. 意图识别（规则解析 + Prompt 约束）+ 图谱查询执行
2. 图谱统计仪表盘：节点数、关系数、各标签分布
3. CRUD 演示面板：创建/更新/删除 实体与关系
4. 多条件查询面板：精准/模糊/区间/IN/OR 组合
5. 关系链路检索：邻居查询、最短路径、兴趣推荐
6. Gradio 网页交互界面（多 Tab 设计）

启动：
    python gradio_app.py
访问：
    http://127.0.0.1:7861（默认端口，可通过 .env 中 NEO4J_GRADIO_PORT 修改）
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
from pathlib import Path
from typing import Any, Optional

import gradio as gr
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
plt.rcParams["font.sans-serif"] = ["SimHei", "Microsoft YaHei", "SimSun"]
plt.rcParams["axes.unicode_minus"] = False
import networkx as nx
from dotenv import load_dotenv

# 加载项目根 .env
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(_PROJECT_ROOT / ".env")

# 确保能 import crud_service
sys.path.insert(0, str(Path(__file__).parent))
from crud_service import KidoGraphService  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
logger = logging.getLogger("kidoai.neo4j.gradio")

# 系统级提示词（用于意图识别约束）
INTENT_PROMPT = """
【角色定义】
你是 KidoAI 知识图谱查询智能体。你的唯一职责是解析用户关于儿童探索轨迹、
兴趣图谱及多模态知识链条的查询请求。

【识别规则】
1. 判断用户是否在查询以下内容：
   - 某个儿童/物体/兴趣/知识/事件的名称
   - 某种图谱关系（LIKES / DISCOVERED / TRIGGERED / LEADS_TO / ASKED_ABOUT）
2. 可处理请求 → 输出：{"name": "实体名称", "relation": "关系类型"}
3. 其他请求（写诗、算术、聊天、天气等）→ 判定为"无法处理"

【无法处理话术】
对不起，作为 KidoAI 知识图谱查询智能体，我无法处理该需求。
我目前仅支持针对儿童探索轨迹、兴趣图谱及知识链条的查询与分析。
"""

# Neo4j 服务（连接失败时降级为离线模式）
_service: Optional[KidoGraphService] = None
try:
    _service = KidoGraphService()
    _service.verify_connectivity()
    logger.info("Neo4j 连接成功：%s", os.getenv("NEO4J_URI", "bolt://127.0.0.1:7687"))
except Exception as e:
    logger.warning("Neo4j 连接失败，将以离线模式运行: %s", e)
    _service = None


# ==========================================
# 1. 智能体意图识别与图谱查询
# ==========================================

# 关系词 → 关系类型映射
RELATION_MAPPING = {
    "喜欢": "LIKES", "偏好": "LIKES", "兴趣": "LIKES", "爱好": "LIKES",
    "发现": "DISCOVERED", "探索": "DISCOVERED", "观察到": "DISCOVERED",
    "识别": "TRIGGERED", "触发": "TRIGGERED", "拍照": "TRIGGERED",
    "引导": "LEADS_TO", "关联": "LEADS_TO", "引申": "LEADS_TO", "链接": "LEADS_TO",
    "提问": "ASKED_ABOUT", "问过": "ASKED_ABOUT", "问": "ASKED_ABOUT",
}

# 已知实体库（用于精准与模糊识别）
KNOWN_ENTITIES = [
    "张小明", "李妙妙", "王博文", "赵可儿", "陈子轩", "周雨桐", "钱浩宇", "孙雅馨", "吴睿博", "郑一诺",
    "霸王龙", "月亮", "蜻蜓", "小丑鱼", "机器人", "含羞草", "彩虹", "火山", "羽毛", "金字塔",
    "恐龙世界", "浩瀚宇宙", "昆虫王国", "海底总动员", "机器人总动员", "绿色植物", "天气奥秘",
    "疯狂化学", "鸟类天堂", "古文明",
    "暴龙特征", "月球环形山", "昆虫复眼", "海葵共生", "舵机", "植物细胞", "光的折射",
    "酸碱中和", "中空骨骼", "金字塔工程",
]


def query_agent_process(user_input: str) -> str:
    """智能体核心处理函数：意图识别 → 参数提取 → 图谱检索 → 结果渲染。"""
    user_input = (user_input or "").strip()
    if not user_input:
        return "请输入您的问题。"

    # 1. 意图识别与参数提取
    extracted_name: Optional[str] = None
    extracted_rels: list[str] = []
    is_valid_query = False

    # 检查关系词
    for kw, rel in RELATION_MAPPING.items():
        if kw in user_input or rel.lower() in user_input.lower():
            is_valid_query = True
            if rel not in extracted_rels:
                extracted_rels.append(rel)

    # 检查实体词
    for entity in KNOWN_ENTITIES:
        if entity in user_input:
            is_valid_query = True
            if not extracted_name:
                extracted_name = entity
            break

    # 兼容查询动词
    if any(q in user_input for q in ["查", "搜索", "寻找", "列表", "谁", "什么", "哪些"]):
        is_valid_query = True

    # 2. 拦截非图谱查询
    if not is_valid_query:
        return (
            "对不起，作为 KidoAI 知识图谱查询智能体，我无法处理该需求。\n"
            "我目前仅支持针对儿童探索轨迹、兴趣图谱及知识链条的查询与分析。"
        )

    # 3. 构造响应
    name_str = extracted_name if extracted_name else "未指定具体实体"
    rels_str = str(extracted_rels) if extracted_rels else "[]"
    lines = [
        f"🔍 意图识别结果 → 名称: {name_str}, 关系: {rels_str}",
        "",
        "正在为您检索图谱数据...",
        "",
    ]

    # 4. 调用后端数据库服务进行检索
    if _service is None:
        lines.append("💡 (当前处于离线演示模式) 模拟图谱返回结果：")
        if "张小明" in name_str:
            lines.append(" - [Child] 张小明 (6岁, 男) -[LIKES]-> [Interest] 恐龙世界")
            lines.append(" - [Child] 张小明 -[DISCOVERED]-> [Object] 霸王龙玩具")
        elif "霸王龙" in name_str:
            lines.append(" - [Object] 霸王龙玩具 -[LEADS_TO]-> [Knowledge] 暴龙特征与食性")
        else:
            lines.append(" - [Object] 蜻蜓标本 -[LEADS_TO]-> [Knowledge] 昆虫复眼构造")
        return "\n".join(lines)

    try:
        search_results: list[dict] = []
        if extracted_name:
            # 模糊搜索该名称
            search_results = _service.advanced_search(fuzzy_conds={"name": extracted_name}, limit=20)
        else:
            # 无具体名称时返回部分数据
            search_results = _service.advanced_search(limit=10)

        if not search_results:
            lines.append("ℹ️ 未在 Neo4j 图数据库中匹配到具体实体数据。")
            lines.append("提示：请先运行 init_db.py 初始化数据库，或换个关键词。")
        else:
            lines.append(f"✨ 成功找到 {len(search_results)} 个匹配的图谱节点：")
            for idx, node in enumerate(search_results, 1):
                labels = ", ".join(node.get("_labels", []))
                name = node.get("name", "无名")
                node_id = node.get("id", "未知")
                other_props = {k: v for k, v in node.items()
                               if k not in ("_labels", "name", "id")}
                lines.append(f"  {idx}. [{labels}] ID: {node_id} | 名称: {name} | 属性: {other_props}")

            # 若识别到具体实体且有关系词，进一步查询邻居
            if extracted_name and extracted_rels and search_results:
                first = search_results[0]
                labels = first.get("_labels", [])
                first_label = labels[0] if labels else None
                first_id = first.get("id")
                if first_label and first_id:
                    neighbors = _service.get_neighbors(
                        first_label, first_id,
                        direction="out",
                        rel_type=extracted_rels[0],
                        limit=10,
                    )
                    if neighbors:
                        lines.append("")
                        lines.append(f"🔗 通过关系 [{extracted_rels[0]}] 关联的邻居节点：")
                        for n in neighbors:
                            node = n["node"]
                            nlabels = ", ".join(node.get("_labels", []))
                            nname = node.get("name", "无名")
                            lines.append(f"  → [{nlabels}] {nname}")
    except Exception as e:
        logger.exception("图谱检索失败")
        lines.append(f"❌ 检索执行出错: {e}")

    return "\n".join(lines)


# ==========================================
# 2. 图谱统计仪表盘
# ==========================================

def get_stats_text() -> str:
    """获取图谱统计信息文本。"""
    if _service is None:
        return "⚠️ Neo4j 未连接，无法获取统计信息。"
    try:
        stats = _service.get_graph_stats()
        lines = [
            "📊 KidoAI 知识图谱统计",
            "=" * 40,
            f"节点总数: {stats['total_nodes']}",
            f"关系总数: {stats['total_relationships']}",
            "",
            "节点标签分布：",
        ]
        for label, cnt in stats["labels"].items():
            lines.append(f"  - {label}: {cnt}")
        lines.append("")
        lines.append("关系类型分布：")
        for rtype, cnt in stats["relationship_types"].items():
            lines.append(f"  - {rtype}: {cnt}")
        return "\n".join(lines)
    except Exception as e:
        return f"❌ 获取统计失败: {e}"


# ==========================================
# 3. CRUD 演示面板
# ==========================================

def crud_create_entity(label: str, entity_id: str, name: str,
                       age: str, gender: str, category: str,
                       weight: str, summary: str, difficulty: str) -> str:
    """创建实体演示。"""
    if _service is None:
        return "⚠️ Neo4j 未连接"
    if not label or not entity_id:
        return "❌ Label 和 ID 必填"
    props: dict[str, Any] = {"id": entity_id}
    if name:
        props["name"] = name
    if age:
        try:
            props["age"] = int(age)
        except ValueError:
            return "❌ age 必须是整数"
    if gender:
        props["gender"] = gender
    if category:
        props["category"] = category
    if weight:
        try:
            props["weight"] = float(weight)
        except ValueError:
            return "❌ weight 必须是数字"
    if summary:
        props["summary"] = summary
    if difficulty:
        props["difficulty_level"] = difficulty
    try:
        result = _service.create_entity(label, props)
        return f"✅ 创建成功\n{json.dumps(result, ensure_ascii=False, indent=2)}"
    except Exception as e:
        return f"❌ 创建失败: {e}"


def crud_update_entity(label: str, entity_id: str, prop_json: str) -> str:
    """更新实体属性（属性以 JSON 提供）。"""
    if _service is None:
        return "⚠️ Neo4j 未连接"
    if not label or not entity_id or not prop_json:
        return "❌ Label / ID / 属性JSON 都必填"
    try:
        props = json.loads(prop_json)
    except json.JSONDecodeError as e:
        return f"❌ 属性 JSON 解析失败: {e}"
    try:
        result = _service.update_entity(label, entity_id, props)
        return f"✅ 更新完成\n{json.dumps(result, ensure_ascii=False, indent=2)}"
    except Exception as e:
        return f"❌ 更新失败: {e}"


def crud_delete_entity(label: str, entity_id: str) -> str:
    """删除实体（DETACH DELETE）。"""
    if _service is None:
        return "⚠️ Neo4j 未连接"
    if not label or not entity_id:
        return "❌ Label 和 ID 必填"
    try:
        result = _service.delete_entity(label, entity_id)
        return f"✅ 删除完成\n{json.dumps(result, ensure_ascii=False, indent=2)}"
    except Exception as e:
        return f"❌ 删除失败: {e}"


def crud_create_relationship(start_label: str, start_id: str,
                             end_label: str, end_id: str,
                             rel_type: str, rel_props_json: str) -> str:
    """创建关系。"""
    if _service is None:
        return "⚠️ Neo4j 未连接"
    if not all([start_label, start_id, end_label, end_id, rel_type]):
        return "❌ 起/止 Label、ID 和关系类型都必填"
    props: dict[str, Any] = {}
    if rel_props_json:
        try:
            props = json.loads(rel_props_json)
        except json.JSONDecodeError as e:
            return f"❌ 关系属性 JSON 解析失败: {e}"
    try:
        result = _service.create_relationship(
            start_label, start_id, end_label, end_id, rel_type, props)
        return f"✅ 关系创建成功\n{json.dumps(result, ensure_ascii=False, indent=2)}"
    except Exception as e:
        return f"❌ 创建关系失败: {e}"


def crud_delete_relationship(start_label: str, start_id: str,
                             end_label: str, end_id: str,
                             rel_type: str) -> str:
    """删除关系。"""
    if _service is None:
        return "⚠️ Neo4j 未连接"
    if not all([start_label, start_id, end_label, end_id, rel_type]):
        return "❌ 所有参数必填"
    try:
        result = _service.delete_relationship(
            start_label, start_id, end_label, end_id, rel_type)
        return f"✅ 删除完成\n{json.dumps(result, ensure_ascii=False, indent=2)}"
    except Exception as e:
        return f"❌ 删除失败: {e}"


# ==========================================
# 4. 多条件查询面板
# ==========================================

def advanced_search_handler(label: str, precise_json: str, fuzzy_json: str,
                             range_json: str, in_json: str, or_json: str,
                             limit: str) -> str:
    """多条件组合查询。"""
    if _service is None:
        return "⚠️ Neo4j 未连接"
    try:
        precise = json.loads(precise_json) if precise_json else None
        fuzzy = json.loads(fuzzy_json) if fuzzy_json else None
        range_conds = json.loads(range_json) if range_json else None
        in_conds = json.loads(in_json) if in_json else None
        or_conds = json.loads(or_json) if or_json else None
        lim = int(limit) if limit else 50
    except json.JSONDecodeError as e:
        return f"❌ JSON 解析失败: {e}"
    try:
        results = _service.advanced_search(
            label=label or None,
            precise_conds=precise,
            fuzzy_conds=fuzzy,
            range_conds=range_conds,
            in_conds=in_conds,
            or_conds=or_conds,
            limit=lim,
        )
        if not results:
            return "ℹ️ 未匹配到任何节点"
        lines = [f"✅ 匹配到 {len(results)} 个节点："]
        for idx, node in enumerate(results, 1):
            labels = ", ".join(node.get("_labels", []))
            name = node.get("name", "无名")
            node_id = node.get("id", "未知")
            other = {k: v for k, v in node.items()
                     if k not in ("_labels", "name", "id")}
            lines.append(f"  {idx}. [{labels}] ID: {node_id} | 名称: {name} | 属性: {other}")
        return "\n".join(lines)
    except Exception as e:
        return f"❌ 查询失败: {e}"


# ==========================================
# 5. 关系链路检索
# ==========================================

def neighbors_handler(label: str, entity_id: str, direction: str,
                      rel_type: str, limit: str) -> str:
    """邻居查询。"""
    if _service is None:
        return "⚠️ Neo4j 未连接"
    if not label or not entity_id:
        return "❌ Label 和 ID 必填"
    try:
        lim = int(limit) if limit else 20
        neighbors = _service.get_neighbors(
            label, entity_id,
            direction=direction or "both",
            rel_type=rel_type or None,
            limit=lim,
        )
        if not neighbors:
            return "ℹ️ 未找到邻居节点"
        lines = [f"✅ 找到 {len(neighbors)} 个邻居："]
        for idx, n in enumerate(neighbors, 1):
            node = n["node"]
            labels = ", ".join(node.get("_labels", []))
            name = node.get("name", "无名")
            node_id = node.get("id", "未知")
            lines.append(
                f"  {idx}. [{labels}] ID: {node_id} | 名称: {name} "
                f"| 关系: {n['rel_type']} | 关系属性: {n['rel_props']}"
            )
        return "\n".join(lines)
    except Exception as e:
        return f"❌ 查询失败: {e}"


def paths_handler(s_label: str, s_id: str, e_label: str, e_id: str,
                  max_depth: str) -> str:
    """最短路径查询。"""
    if _service is None:
        return "⚠️ Neo4j 未连接"
    if not all([s_label, s_id, e_label, e_id]):
        return "❌ 起止 Label 和 ID 必填"
    try:
        depth = int(max_depth) if max_depth else 4
        paths = _service.find_paths(s_label, s_id, e_label, e_id, depth)
        if not paths:
            return "ℹ️ 未找到连通路径"
        lines = [f"✅ 找到 {len(paths)} 条路径："]
        for idx, path in enumerate(paths, 1):
            node_names = [n.get("name", n.get("id", "?")) for n in path]
            lines.append(f"  路径 {idx} (长度 {len(path)-1}): {' → '.join(node_names)}")
        return "\n".join(lines)
    except Exception as e:
        return f"❌ 查询失败: {e}"


def recommend_handler(child_id: str, top_k: str) -> str:
    """兴趣推荐。"""
    if _service is None:
        return "⚠️ Neo4j 未连接"
    if not child_id:
        return "❌ child_id 必填"
    try:
        k = int(top_k) if top_k else 5
        recs = _service.recommend_interests(child_id, k)
        if not recs:
            return "ℹ️ 暂无推荐兴趣"
        lines = [f"✅ 为儿童 {child_id} 推荐兴趣 {len(recs)} 个："]
        for idx, rec in enumerate(recs, 1):
            name = rec.get("name", "无名")
            cat = rec.get("category", "")
            weight = rec.get("weight", 0)
            lines.append(f"  {idx}. {name} | 类别: {cat} | 权重: {weight}")
        return "\n".join(lines)
    except Exception as e:
        return f"❌ 推荐失败: {e}"


# ==========================================
# 5.5 图可视化
# ==========================================

_LABEL_COLORS = {
    "Child": "#4CAF50",
    "Interest": "#FF9800",
    "Object": "#2196F3",
    "Knowledge": "#9C27B0",
    "Event": "#F44336",
}

def _build_graph_plot(limit: int = 200) -> Any:
    if _service is None:
        raise RuntimeError("Neo4j 未连接")
    data = _service.get_graph_data(limit=limit)
    nodes = data.get("nodes", [])
    edges = data.get("edges", [])

    G = nx.DiGraph()
    for node in nodes:
        G.add_node(
            node["id"],
            label=node.get("name", node["id"]),
            group=node.get("group", "Node"),
            full_labels=node.get("labels", []),
        )
    for edge in edges:
        src = edge.get("source")
        tgt = edge.get("target")
        if src and tgt:
            G.add_edge(src, tgt, type=edge.get("type", ""))

    if G.number_of_nodes() == 0:
        fig, ax = plt.subplots(figsize=(6, 3))
        ax.text(0.5, 0.5, "图谱暂无数据，请先在 CRUD 中创建节点与关系", ha="center", va="center")
        ax.axis("off")
        return fig

    fig, ax = plt.subplots(figsize=(10, 7))
    pos = nx.spring_layout(G, seed=42, k=0.6 / max(1, (G.number_of_nodes()) ** 0.5))

    node_colors = []
    for nid in G.nodes():
        labels = G.nodes[nid].get("full_labels", [])
        primary = labels[0] if labels else "Node"
        node_colors.append(_LABEL_COLORS.get(primary, "#BDBDBD"))

    nx.draw_networkx_edges(G, pos, ax=ax, arrows=True, arrowstyle="-|>", arrowsize=14, alpha=0.6)
    nx.draw_networkx_nodes(G, pos, ax=ax, node_color=node_colors, node_size=900, alpha=0.95)
    nx.draw_networkx_labels(
        G, pos,
        labels={nid: G.nodes[nid].get("label", nid) for nid in G.nodes()},
        ax=ax,
        font_size=9,
        font_color="white",
        font_weight="bold",
    )

    if edges:
        seen: dict[str, int] = {}
        unique_edges = []
        for e in edges:
            key = (e.get("source"), e.get("target"), e.get("type"))
            seen[key] = seen.get(key, 0) + 1
            unique_edges.append((key, e))
        shown = {k: 0 for k, _ in unique_edges}
        for (key, e) in unique_edges:
            s, t, rtype = key
            shown[key] += 1
            x1, y1 = pos[s]
            x2, y2 = pos[t]
            mx, my = (x1 + x2) / 2, (y1 + y2) / 2
            ax.text(
                mx, my,
                f"{rtype}·{shown[key]}",
                fontsize=7,
                color="#37474F",
                ha="center",
                va="center",
                bbox=dict(facecolor="white", alpha=0.7, pad=1, edgecolor="none"),
            )

    ax.set_title("KidoAI 知识图谱可视化", fontsize=14)
    ax.axis("off")
    fig.tight_layout()
    return fig

def visualize_graph(limit: str = "200") -> Any:
    try:
        lim = int(limit) if limit else 200
        return _build_graph_plot(limit=lim)
    except Exception as e:
        logger.exception("图谱可视化失败")
        fig, ax = plt.subplots(figsize=(6, 3))
        ax.text(0.5, 0.5, f"可视化失败: {e}", ha="center", va="center")
        ax.axis("off")
        return fig


# ==========================================
# 6. Gradio 界面设计
# ==========================================

def build_ui() -> gr.Blocks:
    """构建 Gradio 多 Tab 界面。"""
    with gr.Blocks(
        title="KidoAI 知识图谱智能体 (Neo4j)",
        theme=gr.themes.Soft(primary_hue="emerald", secondary_hue="blue"),
        css="""
        .header-banner {
            background: linear-gradient(135deg, #11998e 0%, #38ef7d 100%);
            color: white; padding: 20px; border-radius: 12px;
            text-align: center; margin-bottom: 16px;
        }
        .header-banner h1 { margin: 0; font-size: 24px; }
        .header-banner p { margin: 8px 0 0; opacity: 0.9; font-size: 14px; }
        """,
    ) as demo:
        gr.HTML("""
        <div class="header-banner">
            <h1>🌟 KidoAI 长期语义记忆智能体 (Neo4j)</h1>
            <p>基于「儿童兴趣 × 多模态知识链条」图谱，提供查询、CRUD、多条件检索与关系链路分析</p>
        </div>
        """)

        with gr.Tabs():
            # ── Tab 1: 智能体对话 ─────────────────────────────
            with gr.Tab("🤖 智能体查询"):
                with gr.Row():
                    with gr.Column(scale=2):
                        user_input = gr.Textbox(
                            label="💬 请输入您的问题",
                            placeholder="例如：'张小明喜欢什么'、'查一查蜻蜓相关的知识点'、'霸王龙引导到哪些知识'",
                            lines=3,
                        )
                        submit_btn = gr.Button("🤖 执行意图解析与图谱查询", variant="primary")
                    with gr.Column(scale=3):
                        agent_output = gr.Textbox(
                            label="🎯 智能体响应",
                            interactive=False,
                            lines=15,
                        )
                gr.Markdown("""
                ### 💡 体验提示
                - **正向查询**：`张小明喜欢什么`、`蜻蜓标本发现了什么`、`搜索霸王龙`
                - **反向拦截**：`帮我写首诗`、`明天天气如何` → 严格拦截返回无法处理声明
                """)
                submit_btn.click(fn=query_agent_process, inputs=[user_input], outputs=[agent_output])

            # ── Tab 2: 图谱可视化 ────────────────────────────────
            with gr.Tab("🕸️ 图谱可视化"):
                gr.Markdown("### 知识图谱可视化")
                with gr.Row():
                    viz_limit = gr.Textbox(label="关系条数上限", value="200")
                    viz_btn = gr.Button("🔄 刷新可视化", variant="primary")
                viz_out = gr.Plot(label="图谱图")
                viz_btn.click(fn=visualize_graph, inputs=[viz_limit], outputs=[viz_out])
                gr.Markdown("""
                - 颜色：Child=绿色、Interest=橙色、Object=蓝色、Knowledge=紫色、Event=红色
                - 关系标签会显示在连线中点，可直观查看图谱结构
                """)

            # ── Tab 3: 实体 CRUD ──────────────────────────────
            with gr.Tab("📝 实体 CRUD"):
                gr.Markdown("### 创建实体")
                with gr.Row():
                    c_label = gr.Textbox(label="Label", value="Child",
                                         info="可选: Child/Interest/Object/Knowledge/Event")
                    c_id = gr.Textbox(label="ID (必填)", value="C011")
                    c_name = gr.Textbox(label="名称", value="测试儿童")
                with gr.Row():
                    c_age = gr.Textbox(label="age (整数)", value="")
                    c_gender = gr.Textbox(label="gender", value="")
                    c_category = gr.Textbox(label="category", value="")
                with gr.Row():
                    c_weight = gr.Textbox(label="weight (数字)", value="")
                    c_summary = gr.Textbox(label="summary", value="")
                    c_difficulty = gr.Textbox(label="difficulty_level", value="")
                create_btn = gr.Button("➕ 创建实体", variant="primary")
                create_out = gr.Textbox(label="结果", lines=8, interactive=False)
                create_btn.click(
                    fn=crud_create_entity,
                    inputs=[c_label, c_id, c_name, c_age, c_gender,
                            c_category, c_weight, c_summary, c_difficulty],
                    outputs=[create_out],
                )

                gr.Markdown("### 更新实体属性（传入 JSON）")
                with gr.Row():
                    u_label = gr.Textbox(label="Label", value="Child")
                    u_id = gr.Textbox(label="ID", value="C011")
                    u_props = gr.Textbox(label="属性 JSON", value='{"age": 7, "name": "新名字"}')
                update_btn = gr.Button("✏️ 更新实体")
                update_out = gr.Textbox(label="结果", lines=6, interactive=False)
                update_btn.click(
                    fn=crud_update_entity,
                    inputs=[u_label, u_id, u_props],
                    outputs=[update_out],
                )

                gr.Markdown("### 删除实体（DETACH DELETE 连带删除关系）")
                with gr.Row():
                    d_label = gr.Textbox(label="Label", value="Child")
                    d_id = gr.Textbox(label="ID", value="C011")
                delete_btn = gr.Button("🗑️ 删除实体", variant="stop")
                delete_out = gr.Textbox(label="结果", lines=6, interactive=False)
                delete_btn.click(
                    fn=crud_delete_entity,
                    inputs=[d_label, d_id],
                    outputs=[delete_out],
                )

            # ── Tab 4: 关系 CRUD ──────────────────────────────
            with gr.Tab("🔗 关系 CRUD"):
                gr.Markdown("### 创建关系")
                with gr.Row():
                    r_s_label = gr.Textbox(label="起点 Label", value="Child")
                    r_s_id = gr.Textbox(label="起点 ID", value="C001")
                    r_e_label = gr.Textbox(label="终点 Label", value="Interest")
                    r_e_id = gr.Textbox(label="终点 ID", value="I001")
                with gr.Row():
                    r_type = gr.Textbox(label="关系类型",
                                        value="LIKES",
                                        info="可选: LIKES/DISCOVERED/TRIGGERED/LEADS_TO/ASKED_ABOUT")
                    r_props = gr.Textbox(label="关系属性 JSON",
                                         value='{"weight": 90, "first_time": "2026-07-01"}')
                r_create_btn = gr.Button("🔗 创建关系", variant="primary")
                r_create_out = gr.Textbox(label="结果", lines=8, interactive=False)
                r_create_btn.click(
                    fn=crud_create_relationship,
                    inputs=[r_s_label, r_s_id, r_e_label, r_e_id, r_type, r_props],
                    outputs=[r_create_out],
                )

                gr.Markdown("### 删除关系")
                with gr.Row():
                    rd_s_label = gr.Textbox(label="起点 Label", value="Child")
                    rd_s_id = gr.Textbox(label="起点 ID", value="C001")
                    rd_e_label = gr.Textbox(label="终点 Label", value="Interest")
                    rd_e_id = gr.Textbox(label="终点 ID", value="I001")
                    rd_type = gr.Textbox(label="关系类型", value="LIKES")
                r_del_btn = gr.Button("✂️ 删除关系", variant="stop")
                r_del_out = gr.Textbox(label="结果", lines=6, interactive=False)
                r_del_btn.click(
                    fn=crud_delete_relationship,
                    inputs=[rd_s_label, rd_s_id, rd_e_label, rd_e_id, rd_type],
                    outputs=[r_del_out],
                )

            # ── Tab 5: 多条件查询 ──────────────────────────────
            with gr.Tab("🔎 多条件查询"):
                gr.Markdown("### 高级多条件组合查询（所有条件 AND 组合）")
                a_label = gr.Textbox(label="Label (可选)", value="")
                a_precise = gr.Textbox(label='精准匹配 JSON，如 {"name":"张小明"}', value="")
                a_fuzzy = gr.Textbox(label='模糊匹配 JSON，如 {"name":"恐龙"}', value="")
                a_range = gr.Textbox(label='区间 JSON，如 {"age": [4, 7]}', value="")
                a_in = gr.Textbox(label='IN JSON，如 {"category": ["古生物", "天文学"]}', value="")
                a_or = gr.Textbox(label='OR JSON，如 {"name": "霸王龙", "category": "昆虫学"}', value="")
                a_limit = gr.Textbox(label="返回上限", value="50")
                a_btn = gr.Button("🔍 执行查询", variant="primary")
                a_out = gr.Textbox(label="查询结果", lines=20, interactive=False)
                a_btn.click(
                    fn=advanced_search_handler,
                    inputs=[a_label, a_precise, a_fuzzy, a_range, a_in, a_or, a_limit],
                    outputs=[a_out],
                )

            # ── Tab 6: 关系链路检索 ───────────────────────────
            with gr.Tab("🛤️ 关系链路"):
                gr.Markdown("### 邻居查询")
                with gr.Row():
                    n_label = gr.Textbox(label="Label", value="Child")
                    n_id = gr.Textbox(label="ID", value="C001")
                    n_dir = gr.Dropdown(
                        choices=["out", "in", "both"], value="both",
                        label="方向",
                    )
                    n_rel = gr.Textbox(label="关系类型 (可选)", value="")
                    n_limit = gr.Textbox(label="上限", value="20")
                n_btn = gr.Button("🔗 查询邻居", variant="primary")
                n_out = gr.Textbox(label="邻居结果", lines=12, interactive=False)
                n_btn.click(
                    fn=neighbors_handler,
                    inputs=[n_label, n_id, n_dir, n_rel, n_limit],
                    outputs=[n_out],
                )

                gr.Markdown("### 最短路径")
                with gr.Row():
                    p_s_label = gr.Textbox(label="起点 Label", value="Child")
                    p_s_id = gr.Textbox(label="起点 ID", value="C001")
                    p_e_label = gr.Textbox(label="终点 Label", value="Knowledge")
                    p_e_id = gr.Textbox(label="终点 ID", value="K001")
                    p_depth = gr.Textbox(label="最大深度", value="4")
                p_btn = gr.Button("🛤️ 查找路径", variant="primary")
                p_out = gr.Textbox(label="路径结果", lines=10, interactive=False)
                p_btn.click(
                    fn=paths_handler,
                    inputs=[p_s_label, p_s_id, p_e_label, p_e_id, p_depth],
                    outputs=[p_out],
                )

                gr.Markdown("### 兴趣推荐")
                with gr.Row():
                    rec_child = gr.Textbox(label="儿童 ID", value="C001")
                    rec_top = gr.Textbox(label="推荐数量", value="5")
                rec_btn = gr.Button("🎯 推荐兴趣", variant="primary")
                rec_out = gr.Textbox(label="推荐结果", lines=10, interactive=False)
                rec_btn.click(
                    fn=recommend_handler,
                    inputs=[rec_child, rec_top],
                    outputs=[rec_out],
                )

        gr.HTML("""
        <div style="text-align:center; margin-top:16px; color:#888; font-size:12px;">
            KidoAI 知识图谱模块 · Neo4j + Gradio · 支持 5 类实体 5 类关系 4 种复杂查询
        </div>
        """)

    return demo


def main() -> None:
    # 清除代理环境变量：Gradio 启动时会 HEAD http://127.0.0.1:port/ 验证本地可访问性，
    # 若系统设置了 HTTP_PROXY/HTTPS_PROXY，httpx 会走代理导致 503，从而触发
    # "When localhost is not accessible" 错误。清除代理后即可直连本地。
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
        os.environ.pop(key, None)
    # 代理豁免本地地址
    os.environ["NO_PROXY"] = "127.0.0.1,localhost"
    os.environ["no_proxy"] = "127.0.0.1,localhost"

    host = os.getenv("NEO4J_GRADIO_HOST", "127.0.0.1")
    port = int(os.getenv("NEO4J_GRADIO_PORT", "7861"))
    logger.info("启动 KidoAI 知识图谱智能体 (Gradio host=%s port=%d)", host, port)
    app = build_ui()
    app.launch(server_name=host, server_port=port, share=False, inbrowser=False)


if __name__ == "__main__":
    main()
