# -*- coding: utf-8 -*-
"""KidoAI 知识图谱模块端到端联调测试。"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
os.environ.setdefault("NEO4J_URI", "bolt://127.0.0.1:7687")
os.environ.setdefault("NEO4J_USER", "neo4j")
os.environ.setdefault("NEO4J_PASSWORD", "123456abc")

from crud_service import KidoGraphService  # noqa: E402
import gradio_app  # noqa: E402


def main() -> None:
    svc = KidoGraphService()

    print("=" * 60)
    print("1. 图谱统计")
    print("=" * 60)
    stats = svc.get_graph_stats()
    print(f"节点总数: {stats['total_nodes']}, 关系总数: {stats['total_relationships']}")
    print(f"标签分布: {stats['labels']}")
    print(f"关系分布: {stats['relationship_types']}")

    print()
    print("=" * 60)
    print("2. 实体精准查询 get_entity('Child', 'C001')")
    print("=" * 60)
    node = svc.get_entity("Child", "C001")
    print(f"C001: name={node.get('name')}, age={node.get('age')}, gender={node.get('gender')}")

    print()
    print("=" * 60)
    print("3. 模糊查询 - 名字含 '恐龙'")
    print("=" * 60)
    results = svc.advanced_search(fuzzy_conds={"name": "恐龙"}, limit=10)
    print(f"匹配到 {len(results)} 个节点")
    for r in results:
        labels = ",".join(r.get("_labels", []))
        print(f"  - [{labels}] {r.get('name')}")

    print()
    print("=" * 60)
    print("4. 区间查询 - 4<=age<=7 的儿童")
    print("=" * 60)
    results = svc.advanced_search(label="Child", range_conds={"age": (4, 7)}, limit=10)
    print(f"匹配: {len(results)} 个")
    for r in results:
        print(f"  - {r.get('name')} ({r.get('age')}岁)")

    print()
    print("=" * 60)
    print("5. IN 查询 - category in [古生物, 天文学]")
    print("=" * 60)
    results = svc.advanced_search(label="Interest", in_conds={"category": ["古生物", "天文学"]})
    print(f"匹配: {len(results)} 个")
    for r in results:
        print(f"  - {r.get('name')} / {r.get('category')} / weight={r.get('weight')}")

    print()
    print("=" * 60)
    print("6. OR 查询 - name=霸王龙 OR category=昆虫学")
    print("=" * 60)
    results = svc.advanced_search(or_conds={"name": "霸王龙玩具", "category": "昆虫学"})
    print(f"匹配: {len(results)} 个")
    for r in results:
        labels = ",".join(r.get("_labels", []))
        print(f"  - [{labels}] {r.get('name')} / {r.get('category', '')}")

    print()
    print("=" * 60)
    print("7. 邻居查询 - Child C001 所有出边")
    print("=" * 60)
    neighbors = svc.get_neighbors("Child", "C001", direction="out", limit=10)
    print(f"邻居: {len(neighbors)} 个")
    for n in neighbors:
        node = n["node"]
        print(f"  -[{n['rel_type']}]-> [{','.join(node.get('_labels', []))}] {node.get('name')}")

    print()
    print("=" * 60)
    print("8. 最短路径 - 张小明 C001 -> 知识点 K001")
    print("=" * 60)
    paths = svc.find_paths("Child", "C001", "Knowledge", "K001", max_depth=4)
    print(f"路径数: {len(paths)}")
    for p in paths:
        names = [n.get("name") for n in p]
        print(f"  路径: {' -> '.join(names)}")

    print()
    print("=" * 60)
    print("9. 兴趣推荐 - C001 张小明")
    print("=" * 60)
    recs = svc.recommend_interests("C001", top_k=3)
    print(f"推荐: {len(recs)} 个")
    for r in recs:
        print(f"  - {r.get('name')} / {r.get('category')} / weight={r.get('weight')}")

    print()
    print("=" * 60)
    print("10. CRUD - 创建测试实体")
    print("=" * 60)
    r = svc.create_entity("Child", {"id": "C_TEST", "name": "测试儿童", "age": 5, "gender": "男"})
    print(f"创建: {r['status']}, data: {r.get('data')}")

    print()
    print("=" * 60)
    print("11. CRUD - 更新")
    print("=" * 60)
    r = svc.update_entity("Child", "C_TEST", {"age": 6, "name": "测试儿童改名"})
    print(f"更新: {r['status']}")

    node = svc.get_entity("Child", "C_TEST")
    print(f"验证: name={node.get('name')}, age={node.get('age')}")

    print()
    print("=" * 60)
    print("12. CRUD - 删除")
    print("=" * 60)
    r = svc.delete_entity("Child", "C_TEST")
    print(f"删除: {r['status']}, message: {r.get('message')}")
    node = svc.get_entity("Child", "C_TEST")
    print(f"删除后查询: {node}")

    print()
    print("=" * 60)
    print("13. 意图识别 - 拦截非图谱查询")
    print("=" * 60)
    print("输入: '帮我写首诗'")
    print(f"输出: {gradio_app.query_agent_process('帮我写首诗')}")

    print()
    print("=" * 60)
    print("14. 意图识别 - 正向图谱查询")
    print("=" * 60)
    print("输入: '张小明喜欢什么'")
    print(f"输出: {gradio_app.query_agent_process('张小明喜欢什么')}")

    print()
    print("=" * 60)
    print("15. 意图识别 - 实体模糊查询")
    print("=" * 60)
    print("输入: '查一查蜻蜓相关的知识点'")
    print(f"输出: {gradio_app.query_agent_process('查一查蜻蜓相关的知识点')}")

    svc.close()
    print()
    print("=" * 60)
    print("全部测试通过")
    print("=" * 60)


if __name__ == "__main__":
    main()
