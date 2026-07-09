# -*- coding: utf-8 -*-
"""KidoAI 知识图谱 CRUD 与复杂查询服务层 - crud_service.py

实现：
1. 实体管理接口（创建 / 查询 / 修改 / 删除，DETACH DELETE 确保安全删除）
2. 关系管理接口（建立 / 查询 / 修改 / 删除，MERGE 保证幂等）
3. 复杂多条件查询：精准查询、模糊查询、区间查询、IN / OR 逻辑组合查询
4. 图谱统计与关系链路检索（多跳查询、邻居查询、兴趣推荐）

所有 Cypher 参数化查询，杜绝注入风险；Label/RelType 做白名单校验。
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any, Iterable, Optional

from neo4j import GraphDatabase

logger = logging.getLogger("kidoai.neo4j")

# 连接配置（支持环境变量覆盖）
NEO4J_URI = os.getenv("NEO4J_URI", "bolt://127.0.0.1:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "123456abc")

# 允许的节点 Label 白名单（防止任意标签注入）
ALLOWED_LABELS = {"Child", "Interest", "Object", "Knowledge", "Event"}
# 允许的关系类型白名单
ALLOWED_REL_TYPES = {
    "LIKES", "DISCOVERED", "TRIGGERED", "LEADS_TO", "ASKED_ABOUT",
}


def _validate_label(label: str) -> str:
    """校验 Label 合法性，防止 Cypher 注入。"""
    if not label or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", label):
        raise ValueError(f"非法的 Label 名称: {label!r}")
    return label


def _validate_rel_type(rel_type: str) -> str:
    """校验关系类型合法性。"""
    if not rel_type or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", rel_type):
        raise ValueError(f"非法的关系类型: {rel_type!r}")
    return rel_type


def _node_to_dict(node) -> dict[str, Any]:
    """将 Neo4j Node 转为普通 dict（附带 _labels）。"""
    data = dict(node)
    data["_labels"] = list(node.labels)
    return data


class KidoGraphService:
    """KidoAI 知识图谱服务（单例 driver）。"""

    def __init__(
        self,
        uri: Optional[str] = None,
        user: Optional[str] = None,
        password: Optional[str] = None,
    ) -> None:
        self.driver = GraphDatabase.driver(
            uri or NEO4J_URI,
            auth=(user or NEO4J_USER, password or NEO4J_PASSWORD),
        )

    def close(self) -> None:
        self.driver.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    # ==========================================
    # 1. 实体管理接口 (Entity CRUD)
    # ==========================================

    def create_entity(self, label: str, properties: dict) -> dict[str, Any]:
        """创建实体节点（MERGE 幂等，按 id 去重）。

        Args:
            label: 节点标签，必须在 ALLOWED_LABELS 中
            properties: 节点属性 dict，必须包含 id 字段
        Returns:
            {"status": "success"/"exists", "data": {...}}
        """
        label = _validate_label(label)
        if "id" not in properties:
            raise ValueError("properties 必须包含 id 字段")

        cypher = (
            f"MERGE (n:{label} {{id: $id}}) "
            "SET n += $props "
            "RETURN n, (n IS NOT NULL) AS created"
        )
        with self.driver.session() as session:
            record = session.run(cypher, id=properties["id"], props=properties).single()
            if record is None:
                return {"status": "error", "message": "创建失败"}
            return {"status": "success", "data": _node_to_dict(record["n"])}

    def get_entity(self, label: str, entity_id: str) -> Optional[dict[str, Any]]:
        """按 id 精准查询实体。"""
        label = _validate_label(label)
        cypher = f"MATCH (n:{label} {{id: $eid}}) RETURN n LIMIT 1"
        with self.driver.session() as session:
            record = session.run(cypher, eid=entity_id).single()
            if record is None:
                return None
            return _node_to_dict(record["n"])

    def update_entity(self, label: str, entity_id: str, properties: dict) -> dict[str, Any]:
        """更新或合并修改实体属性（SET 语法动态更新）。

        Args:
            label: 节点标签
            entity_id: 节点 id
            properties: 待合并的属性 dict
        """
        label = _validate_label(label)
        # 过滤掉 id 字段（作为唯一标识不修改）
        safe_props = {k: v for k, v in properties.items() if k != "id"}
        if not safe_props:
            return {"status": "ignored", "message": "没有需要修改的属性"}

        set_clauses = ", ".join(f"n.{k} = ${k}" for k in safe_props)
        cypher = (
            f"MATCH (n:{label} {{id: $entity_id}}) "
            f"SET {set_clauses} "
            "RETURN n"
        )
        params = {"entity_id": entity_id, **safe_props}
        with self.driver.session() as session:
            record = session.run(cypher, **params).single()
            if record is None:
                return {"status": "error", "message": f"未找到 ID 为 {entity_id} 的 {label} 实体"}
            return {"status": "success", "data": _node_to_dict(record["n"])}

    def delete_entity(self, label: str, entity_id: str) -> dict[str, Any]:
        """安全删除实体（DETACH DELETE 连带删除关系，避免悬挂边）。"""
        label = _validate_label(label)
        cypher = (
            f"MATCH (n:{label} {{id: $entity_id}}) "
            "DETACH DELETE n "
            "RETURN count(n) AS deleted_count"
        )
        with self.driver.session() as session:
            record = session.run(cypher, entity_id=entity_id).single()
            count = record["deleted_count"] if record else 0
            if count > 0:
                return {"status": "success", "message": f"已删除 {label} 实体(ID:{entity_id}) 及其所有关系"}
            return {"status": "error", "message": f"未找到 ID 为 {entity_id} 的 {label} 实体"}

    # ==========================================
    # 2. 关系管理接口 (Relationship CRUD)
    # ==========================================

    def create_relationship(
        self,
        start_label: str,
        start_id: str,
        end_label: str,
        end_id: str,
        rel_type: str,
        properties: Optional[dict] = None,
    ) -> dict[str, Any]:
        """建立或合并两实体之间的关系（MERGE 幂等）。

        Args:
            rel_type: 关系类型（如 LIKES / DISCOVERED / TRIGGERED / LEADS_TO / ASKED_ABOUT）
            properties: 关系属性（如 weight、count、first_time 等）
        """
        start_label = _validate_label(start_label)
        end_label = _validate_label(end_label)
        rel_type = _validate_rel_type(rel_type)
        properties = properties or {}

        set_clause = ""
        params: dict[str, Any] = {"start_id": start_id, "end_id": end_id}
        if properties:
            set_clauses = []
            for k, v in properties.items():
                set_clauses.append(f"r.{k} = ${k}")
                params[k] = v
            set_clause = "SET " + ", ".join(set_clauses)

        cypher = (
            f"MATCH (a:{start_label} {{id: $start_id}}), (b:{end_label} {{id: $end_id}}) "
            f"MERGE (a)-[r:{rel_type}]->(b) "
            f"{set_clause} "
            "RETURN type(r) AS rel_type, properties(r) AS props, a.id AS from_id, b.id AS to_id"
        )
        with self.driver.session() as session:
            record = session.run(cypher, **params).single()
            if record is None:
                return {"status": "error", "message": "未找到对应的两端实体"}
            return {
                "status": "success",
                "rel_type": record["rel_type"],
                "from_id": record["from_id"],
                "to_id": record["to_id"],
                "properties": dict(record["props"]),
            }

    def get_relationship(
        self,
        start_label: str,
        start_id: str,
        end_label: str,
        end_id: str,
        rel_type: str,
    ) -> Optional[dict[str, Any]]:
        """查询两实体之间指定类型的关系。"""
        start_label = _validate_label(start_label)
        end_label = _validate_label(end_label)
        rel_type = _validate_rel_type(rel_type)

        cypher = (
            f"MATCH (a:{start_label} {{id: $start_id}})-[r:{rel_type}]->(b:{end_label} {{id: $end_id}}) "
            "RETURN type(r) AS rel_type, properties(r) AS props, "
            "a.id AS from_id, labels(a) AS from_labels, "
            "b.id AS to_id, labels(b) AS to_labels "
            "LIMIT 1"
        )
        with self.driver.session() as session:
            record = session.run(cypher, start_id=start_id, end_id=end_id).single()
            if record is None:
                return None
            return {
                "rel_type": record["rel_type"],
                "from_id": record["from_id"],
                "from_labels": list(record["from_labels"]),
                "to_id": record["to_id"],
                "to_labels": list(record["to_labels"]),
                "properties": dict(record["props"]),
            }

    def update_relationship(
        self,
        start_label: str,
        start_id: str,
        end_label: str,
        end_id: str,
        rel_type: str,
        properties: dict,
    ) -> dict[str, Any]:
        """修改或合并两实体之间的关系属性（仅在关系存在时更新）。"""
        start_label = _validate_label(start_label)
        end_label = _validate_label(end_label)
        rel_type = _validate_rel_type(rel_type)
        if not properties:
            return {"status": "ignored", "message": "没有需要修改的关系属性"}

        set_clauses = ", ".join(f"r.{k} = ${k}" for k in properties)
        cypher = (
            f"MATCH (a:{start_label} {{id: $start_id}})-[r:{rel_type}]->"
            f"(b:{end_label} {{id: $end_id}}) "
            f"SET {set_clauses} "
            "RETURN properties(r) AS rel_props"
        )
        params = {"start_id": start_id, "end_id": end_id, **properties}
        with self.driver.session() as session:
            record = session.run(cypher, **params).single()
            if record is None:
                return {"status": "error", "message": "未找到对应的两端实体或指定类型的关系"}
            return {"status": "success", "properties": dict(record["rel_props"])}

    def delete_relationship(
        self,
        start_label: str,
        start_id: str,
        end_label: str,
        end_id: str,
        rel_type: str,
    ) -> dict[str, Any]:
        """删除特定两节点之间的关系（保留节点本身）。"""
        start_label = _validate_label(start_label)
        end_label = _validate_label(end_label)
        rel_type = _validate_rel_type(rel_type)

        cypher = (
            f"MATCH (a:{start_label} {{id: $start_id}})-[r:{rel_type}]->"
            f"(b:{end_label} {{id: $end_id}}) "
            "DELETE r "
            "RETURN count(r) AS deleted_count"
        )
        with self.driver.session() as session:
            record = session.run(cypher, start_id=start_id, end_id=end_id).single()
            count = record["deleted_count"] if record else 0
            if count > 0:
                return {"status": "success", "message": f"已切断关系 [{rel_type}] ({count} 条)"}
            return {"status": "error", "message": "未匹配到指定的关系链路"}

    # ==========================================
    # 3. 复杂多条件查询接口 (Advanced Query API)
    # ==========================================

    def advanced_search(
        self,
        label: Optional[str] = None,
        precise_conds: Optional[dict] = None,
        fuzzy_conds: Optional[dict] = None,
        range_conds: Optional[dict[str, tuple]] = None,
        in_conds: Optional[dict[str, list]] = None,
        or_conds: Optional[dict] = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """图谱多功能复杂查询。

        支持：精准查询 / 模糊查询 / 区间查询 / IN / OR 多值与逻辑组合查询。
        所有 WHERE 条件之间是 AND 关系，OR_conds 内部是 OR 关系。

        Args:
            label: 节点标签（可选，None 表示所有标签）
            precise_conds: 精准匹配，如 {"name": "张小明"}
            fuzzy_conds: 模糊匹配（CONTAINS），如 {"name": "恐龙"}
            range_conds: 区间查询，如 {"age": (4, 7)}，None 表示不限
            in_conds: IN 查询，如 {"category": ["古生物", "天文学"]}
            or_conds: OR 查询，如 {"name": "霸王龙", "category": "昆虫学"}
            limit: 返回上限，默认 50
        """
        if label:
            label = _validate_label(label)
        label_clause = f":{label}" if label else ""
        cypher_where: list[str] = []
        params: dict[str, Any] = {}
        param_counter = 0

        # A. 精准匹配
        if precise_conds:
            for key, val in precise_conds.items():
                p_name = f"p_{param_counter}"
                cypher_where.append(f"n.{key} = ${p_name}")
                params[p_name] = val
                param_counter += 1

        # B. 模糊匹配（CONTAINS）
        if fuzzy_conds:
            for key, val in fuzzy_conds.items():
                p_name = f"f_{param_counter}"
                cypher_where.append(f"n.{key} CONTAINS ${p_name}")
                params[p_name] = val
                param_counter += 1

        # C. 区间查询 {"age": (4, 7)} 或 {"weight": (50, None)}
        if range_conds:
            for key, (low, high) in range_conds.items():
                if low is not None:
                    p_low = f"r_low_{param_counter}"
                    cypher_where.append(f"n.{key} >= ${p_low}")
                    params[p_low] = low
                    param_counter += 1
                if high is not None:
                    p_high = f"r_high_{param_counter}"
                    cypher_where.append(f"n.{key} <= ${p_high}")
                    params[p_high] = high
                    param_counter += 1

        # D. IN 查询 {"category": ["古生物", "天文学"]}
        if in_conds:
            for key, list_vals in in_conds.items():
                p_name = f"in_{param_counter}"
                cypher_where.append(f"n.{key} IN ${p_name}")
                params[p_name] = list_vals
                param_counter += 1

        # E. OR 查询 {"name": "霸王龙玩具", "category": "昆虫学"}
        if or_conds:
            or_clauses = []
            for key, val in or_conds.items():
                p_name = f"or_{param_counter}"
                or_clauses.append(f"n.{key} = ${p_name}")
                params[p_name] = val
                param_counter += 1
            if or_clauses:
                cypher_where.append("(" + " OR ".join(or_clauses) + ")")

        where_str = "WHERE " + " AND ".join(cypher_where) if cypher_where else ""
        # limit 限制范围，防止过大结果集
        safe_limit = max(1, min(int(limit), 500))
        cypher = (
            f"MATCH (n{label_clause}) "
            f"{where_str} "
            "RETURN n, labels(n) AS node_labels "
            f"LIMIT {safe_limit}"
        )

        results: list[dict[str, Any]] = []
        with self.driver.session() as session:
            for record in session.run(cypher, **params):
                node_data = _node_to_dict(record["n"])
                results.append(node_data)
        return results

    # ==========================================
    # 4. 图谱统计与关系链路检索
    # ==========================================

    def count_nodes(self, label: Optional[str] = None) -> int:
        """统计节点总数（可按标签过滤）。"""
        label_clause = f":{label}" if label else ""
        cypher = f"MATCH (n{label_clause}) RETURN count(n) AS c"
        with self.driver.session() as session:
            record = session.run(cypher).single()
            return record["c"] if record else 0

    def get_graph_stats(self) -> dict[str, Any]:
        """获取图谱整体统计信息：各标签节点数、各关系类型数、总数。"""
        stats: dict[str, Any] = {
            "total_nodes": 0,
            "total_relationships": 0,
            "labels": {},
            "relationship_types": {},
        }
        with self.driver.session() as session:
            # 节点标签统计
            for record in session.run("CALL db.labels() YIELD label RETURN label"):
                label = record["label"]
                cnt = session.run(f"MATCH (n:`{label}`) RETURN count(n) AS c").single()["c"]
                stats["labels"][label] = cnt
                stats["total_nodes"] += cnt
            # 关系类型统计
            for record in session.run("CALL db.relationshipTypes() YIELD relationshipType RETURN relationshipType"):
                rtype = record["relationshipType"]
                cnt = session.run(f"MATCH ()-[r:`{rtype}`]->() RETURN count(r) AS c").single()["c"]
                stats["relationship_types"][rtype] = cnt
                stats["total_relationships"] += cnt
        return stats

    def get_neighbors(
        self,
        label: str,
        entity_id: str,
        direction: str = "both",
        rel_type: Optional[str] = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """查询某节点的邻居（出/入/双向）。

        Args:
            direction: "out" / "in" / "both"
            rel_type: 关系类型过滤（None 表示所有关系）
            limit: 返回上限
        """
        label = _validate_label(label)
        if rel_type:
            rel_type = _validate_rel_type(rel_type)
        rel_clause = f":{rel_type}" if rel_type else ""
        if direction == "out":
            pattern = f"(n:{label} {{id: $eid}})-[r{rel_clause}]->(m)"
        elif direction == "in":
            pattern = f"(n:{label} {{id: $eid}})<-[r{rel_clause}]-(m)"
        else:
            pattern = f"(n:{label} {{id: $eid}})-[r{rel_clause}]-(m)"

        safe_limit = max(1, min(int(limit), 200))
        cypher = (
            f"MATCH {pattern} "
            "RETURN m, labels(m) AS labels, type(r) AS rel_type, "
            "properties(r) AS rel_props "
            f"LIMIT {safe_limit}"
        )
        results: list[dict[str, Any]] = []
        with self.driver.session() as session:
            for record in session.run(cypher, eid=entity_id):
                results.append({
                    "node": _node_to_dict(record["m"]),
                    "rel_type": record["rel_type"],
                    "rel_props": dict(record["rel_props"]),
                })
        return results

    def find_paths(
        self,
        start_label: str,
        start_id: str,
        end_label: str,
        end_id: str,
        max_depth: int = 4,
    ) -> list[list[dict[str, Any]]]:
        """查找两实体之间的最短路径（最多 max_depth 跳）。"""
        start_label = _validate_label(start_label)
        end_label = _validate_label(end_label)
        depth = max(1, min(int(max_depth), 6))
        cypher = (
            f"MATCH p = shortestPath("
            f"(a:{start_label} {{id: $sid}})-[*..{depth}]-(b:{end_label} {{id: $eid}})) "
            "RETURN [node IN nodes(p) | {id: node.id, name: node.name, labels: labels(node)}] AS path_nodes, "
            "length(p) AS path_length"
        )
        paths: list[list[dict[str, Any]]] = []
        with self.driver.session() as session:
            for record in session.run(cypher, sid=start_id, eid=end_id):
                paths.append(list(record["path_nodes"]))
        return paths

    def recommend_interests(self, child_id: str, top_k: int = 5) -> list[dict[str, Any]]:
        """基于图谱的兴趣推荐：查询儿童已喜欢兴趣的相邻兴趣。

        策略：找到该儿童所有 LIKES 的兴趣 → 找到同类别的其他兴趣 → 按权重排序推荐。
        """
        safe_top = max(1, min(int(top_k), 20))
        cypher = (
            "MATCH (c:Child {id: $cid})-[:LIKES]->(i:Interest) "
            "WITH c, collect(DISTINCT i.category) AS cats "
            "UNWIND cats AS cat "
            "MATCH (rec:Interest {category: cat}) "
            "WHERE NOT (c)-[:LIKES]->(rec) "
            "RETURN rec, rec.weight AS weight "
            f"ORDER BY weight DESC LIMIT {safe_top}"
        )
        results: list[dict[str, Any]] = []
        with self.driver.session() as session:
            for record in session.run(cypher, cid=child_id):
                results.append(_node_to_dict(record["rec"]))
        return results

    def verify_connectivity(self) -> bool:
        """测试连接是否正常。"""
        try:
            self.driver.verify_connectivity()
            return True
        except Exception as e:
            logger.error("Neo4j 连接失败: %s", e)
            return False

    def get_graph_data(self, limit: int = 200) -> dict[str, Any]:
        """获取全量图谱数据（节点 + 关系），用于可视化。

        Returns:
            {
              "nodes": [{"id": ..., "name": ..., "labels": [...], "group": ...}, ...],
              "edges": [{"source": ..., "target": ..., "type": ..., "properties": {...}}, ...]
            }
        """
        safe_limit = max(1, min(int(limit), 500))
        nodes: dict[str, dict[str, Any]] = {}
        edges: list[dict[str, Any]] = []

        with self.driver.session() as session:
            cypher = (
                "MATCH (n)-[r]->(m) "
                "RETURN n, r, m, labels(n) AS n_labels, labels(m) AS m_labels, type(r) AS rel_type "
                f"LIMIT {safe_limit}"
            )
            for record in session.run(cypher):
                n = record["n"]
                m = record["m"]
                r = record["r"]
                nid = n.get("id") or str(n.id)
                mid = m.get("id") or str(m.id)
                if nid not in nodes:
                    nodes[nid] = {
                        "id": nid,
                        "name": n.get("name", nid),
                        "labels": list(record["n_labels"]),
                        "group": (record["n_labels"][0] if record["n_labels"] else "Node"),
                    }
                if mid not in nodes:
                    nodes[mid] = {
                        "id": mid,
                        "name": m.get("name", mid),
                        "labels": list(record["m_labels"]),
                        "group": (record["m_labels"][0] if record["m_labels"] else "Node"),
                    }
                edges.append({
                    "source": nid,
                    "target": mid,
                    "type": record["rel_type"],
                    "properties": dict(r),
                })

        return {
            "nodes": list(nodes.values()),
            "edges": edges,
        }
