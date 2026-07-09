# -*- coding: utf-8 -*-
"""
KidoAI 知识图谱初始化脚本 - init_db.py
用于创建「儿童兴趣 × 多模态知识链条」的 5 类实体（每类 10 个，共 50 个）及关联关系。
"""

import os
from neo4j import GraphDatabase

# 默认连接配置，支持通过环境变量重写（与 crud_service.py 保持一致）
NEO4J_URI = os.getenv("NEO4J_URI", "bolt://127.0.0.1:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "123456abc")

# 50 个节点的创建 Cypher 语句
CYPHER_CREATE_NODES = """
// 1. 创建 10 个 Child 节点
MERGE (c1:Child {id: "C001", name: "张小明", age: 6, gender: "男", created_at: "2026-01-10"})
MERGE (c2:Child {id: "C002", name: "李妙妙", age: 5, gender: "女", created_at: "2026-02-15"})
MERGE (c3:Child {id: "C003", name: "王博文", age: 7, gender: "男", created_at: "2026-03-01"})
MERGE (c4:Child {id: "C004", name: "赵可儿", age: 4, gender: "女", created_at: "2026-03-20"})
MERGE (c5:Child {id: "C005", name: "陈子轩", age: 8, gender: "男", created_at: "2026-04-05"})
MERGE (c6:Child {id: "C006", name: "周雨桐", age: 6, gender: "女", created_at: "2026-04-12"})
MERGE (c7:Child {id: "C007", name: "钱浩宇", age: 5, gender: "男", created_at: "2026-05-01"})
MERGE (c8:Child {id: "C008", name: "孙雅馨", age: 7, gender: "女", created_at: "2026-05-18"})
MERGE (c9:Child {id: "C009", name: "吴睿博", age: 6, gender: "男", created_at: "2026-06-02"})
MERGE (c10:Child {id: "C010", name: "郑一诺", age: 4, gender: "女", created_at: "2026-06-15"})

// 2. 创建 10 个 Interest 节点
MERGE (i1:Interest {id: "I001", name: "恐龙世界", category: "古生物", weight: 85, updated_at: "2026-07-01"})
MERGE (i2:Interest {id: "I002", name: "浩瀚宇宙", category: "天文学", weight: 90, updated_at: "2026-07-02"})
MERGE (i3:Interest {id: "I003", name: "昆虫王国", category: "昆虫学", weight: 75, updated_at: "2026-07-03"})
MERGE (i4:Interest {id: "I004", name: "海底总动员", category: "海洋生物", weight: 80, updated_at: "2026-07-04"})
MERGE (i5:Interest {id: "I005", name: "机器人总动员", category: "前沿科技", weight: 95, updated_at: "2026-07-05"})
MERGE (i6:Interest {id: "I006", name: "绿色植物", category: "植物学", weight: 65, updated_at: "2026-07-06"})
MERGE (i7:Interest {id: "I007", name: "天气奥秘", category: "地球科学", weight: 70, updated_at: "2026-07-07"})
MERGE (i8:Interest {id: "I008", name: "疯狂化学", category: "物质科学", weight: 60, updated_at: "2026-07-08"})
MERGE (i9:Interest {id: "I009", name: "鸟类天堂", category: "动物学", weight: 72, updated_at: "2026-07-08"})
MERGE (i10:Interest {id: "I010", name: "古文明探秘", category: "历史考古", weight: 88, updated_at: "2026-07-08"})

// 3. 创建 10 个 Object 节点
MERGE (o1:Object {id: "O001", name: "霸王龙玩具", source_image: "img_trex_01.png", confidence: 0.98, detected_at: "2026-07-01"})
MERGE (o2:Object {id: "O002", name: "望远镜月亮", source_image: "img_moon_02.png", confidence: 0.95, detected_at: "2026-07-02"})
MERGE (o3:Object {id: "O003", name: "蜻蜓标本", source_image: "img_dragonfly_03.png", confidence: 0.92, detected_at: "2026-07-03"})
MERGE (o4:Object {id: "O004", name: "小丑鱼鱼缸", source_image: "img_clownfish_04.png", confidence: 0.96, detected_at: "2026-07-04"})
MERGE (o5:Object {id: "O005", name: "乐高机器人", source_image: "img_lego_robot_05.png", confidence: 0.99, detected_at: "2026-07-05"})
MERGE (o6:Object {id: "O006", name: "含羞草叶子", source_image: "img_mimosa_06.png", confidence: 0.91, detected_at: "2026-07-06"})
MERGE (o7:Object {id: "O007", name: "彩虹天空", source_image: "img_rainbow_07.png", confidence: 0.94, detected_at: "2026-07-07"})
MERGE (o8:Object {id: "O008", name: "小苏打火山", source_image: "img_volcano_08.png", confidence: 0.97, detected_at: "2026-07-08"})
MERGE (o9:Object {id: "O009", name: "麻雀羽毛", source_image: "img_sparrow_09.png", confidence: 0.89, detected_at: "2026-07-08"})
MERGE (o10:Object {id: "O010", name: "金字塔积木", source_image: "img_pyramid_10.png", confidence: 0.93, detected_at: "2026-07-08"})

// 4. 创建 10 个 Knowledge 节点
MERGE (k1:Knowledge {id: "K001", name: "暴龙特征与食性", summary: "霸王龙是白垩纪晚期的肉食性恐龙，拥有极其强大的咬合力。", difficulty_level: "中级", category: "古生物"})
MERGE (k2:Knowledge {id: "K002", name: "月球环形山与引力", summary: "月球表面布满环形山，没有大气层，引力仅为地球的六分之一。", difficulty_level: "初级", category: "天文学"})
MERGE (k3:Knowledge {id: "K003", name: "昆虫复眼构造", summary: "蜻蜓的眼睛是复眼，由成千上万只小眼睛组成，视野极广。", difficulty_level: "高级", category: "昆虫学"})
MERGE (k4:Knowledge {id: "K004", name: "小丑鱼与海葵共生", summary: "小丑鱼身上有一层特殊黏液防刺细胞，能与海葵互利共生。", difficulty_level: "初级", category: "海洋生物"})
MERGE (k5:Knowledge {id: "K005", name: "舵机与微控制编程", summary: "机器人通过舵机控制关节运动，编程算法决定其运动行为。", difficulty_level: "高级", category: "前沿科技"})
MERGE (k6:Knowledge {id: "K006", name: "植物细胞与应激性", summary: "含羞草受触碰时，叶柄基部的细胞失去水分导致叶片闭合。", difficulty_level: "中级", category: "植物学"})
MERGE (k7:Knowledge {id: "K007", name: "光的折射与光谱", summary: "彩虹是阳光穿过空中雨滴时，发生折射、反射和色散形成的。", difficulty_level: "中级", category: "地球科学"})
MERGE (k8:Knowledge {id: "K008", name: "酸碱中和化学反应", summary: "小苏打和醋混合会发生强烈的酸碱反应，释放二氧化碳气体。", difficulty_level: "初级", category: "物质科学"})
MERGE (k9:Knowledge {id: "K009", name: "鸟类的中空骨骼与飞行", summary: "鸟类的骨骼大多是中空的，这能大大减轻体重以适应飞行生活。", difficulty_level: "中级", category: "动物学"})
MERGE (k10:Knowledge {id: "K010", name: "古埃及金字塔工程", summary: "金字塔是古埃及法老的陵墓，展现了古代极高的石块搬运与力学智慧。", difficulty_level: "中级", category: "历史考古"})

// 5. 创建 10 个 Event 节点
MERGE (e1:Event {id: "E001", title: "张小明探索恐龙玩具", type: "拍照识别", happened_at: "2026-07-01", source_id: "record_101"})
MERGE (e2:Event {id: "E002", title: "李妙妙观察月亮", type: "天文镜对接", happened_at: "2026-07-02", source_id: "record_102"})
MERGE (e3:Event {id: "E003", title: "王博文探索蜻蜓标本", type: "语音问答", happened_at: "2026-07-03", source_id: "record_103"})
MERGE (e4:Event {id: "E004", title: "赵可儿观察小丑鱼", type: "拍照识别", happened_at: "2026-07-04", source_id: "record_104"})
MERGE (e5:Event {id: "E005", title: "陈子轩组装机器人", type: "传感器读数", happened_at: "2026-07-05", source_id: "record_105"})
MERGE (e6:Event {id: "E006", title: "周雨桐触摸含羞草", type: "拍照识别", happened_at: "2026-07-06", source_id: "record_106"})
MERGE (e7:Event {id: "E007", title: "钱浩宇拍摄彩虹", type: "拍照识别", happened_at: "2026-07-07", source_id: "record_107"})
MERGE (e8:Event {id: "E008", title: "孙雅馨做火山爆发实验", type: "视频记录", happened_at: "2026-07-08", source_id: "record_108"})
MERGE (e9:Event {id: "E009", title: "吴睿博捡到麻雀羽毛", type: "拍照识别", happened_at: "2026-07-08", source_id: "record_109"})
MERGE (e10:Event {id: "E010", title: "郑一诺拼搭金字塔", type: "语音问答", happened_at: "2026-07-08", source_id: "record_110"})
"""

# 建立关联关系的 Cypher 语句 (20 组关系)
CYPHER_CREATE_RELATIONSHIPS = """
// MATCH 各自实体进行连线

// LIKES 关系 (Child -> Interest)
MATCH (c1:Child {id: "C001"}), (i1:Interest {id: "I001"}) MERGE (c1)-[:LIKES {weight: 90, first_time: "2026-01-20", last_active: "2026-07-01"}]->(i1)
MATCH (c2:Child {id: "C002"}), (i2:Interest {id: "I002"}) MERGE (c2)-[:LIKES {weight: 95, first_time: "2026-02-18", last_active: "2026-07-02"}]->(i2)
MATCH (c3:Child {id: "C003"}), (i3:Interest {id: "I003"}) MERGE (c3)-[:LIKES {weight: 80, first_time: "2026-03-05", last_active: "2026-07-03"}]->(i3)
MATCH (c4:Child {id: "C004"}), (i4:Interest {id: "I004"}) MERGE (c4)-[:LIKES {weight: 85, first_time: "2026-03-25", last_active: "2026-07-04"}]->(i4)
MATCH (c5:Child {id: "C005"}), (i5:Interest {id: "I005"}) MERGE (c5)-[:LIKES {weight: 98, first_time: "2026-04-10", last_active: "2026-07-05"}]->(i5)

// DISCOVERED 关系 (Child -> Object)
MATCH (c1:Child {id: "C001"}), (o1:Object {id: "O001"}) MERGE (c1)-[:DISCOVERED {count: 5, first_discovered_at: "2026-07-01"}]->(o1)
MATCH (c2:Child {id: "C002"}), (o2:Object {id: "O002"}) MERGE (c2)-[:DISCOVERED {count: 2, first_discovered_at: "2026-07-02"}]->(o2)
MATCH (c3:Child {id: "C003"}), (o3:Object {id: "O003"}) MERGE (c3)-[:DISCOVERED {count: 3, first_discovered_at: "2026-07-03"}]->(o3)
MATCH (c4:Child {id: "C004"}), (o4:Object {id: "O004"}) MERGE (c4)-[:DISCOVERED {count: 4, first_discovered_at: "2026-07-04"}]->(o4)
MATCH (c5:Child {id: "C005"}), (o5:Object {id: "O005"}) MERGE (c5)-[:DISCOVERED {count: 6, first_discovered_at: "2026-07-05"}]->(o5)

// TRIGGERED 关系 (Event -> Object)
MATCH (e1:Event {id: "E001"}), (o1:Object {id: "O001"}) MERGE (e1)-[:TRIGGERED {method: "camera"}]->(o1)
MATCH (e2:Event {id: "E002"}), (o2:Object {id: "O002"}) MERGE (e2)-[:TRIGGERED {method: "astrotelescope"}]->(o2)
MATCH (e3:Event {id: "E003"}), (o3:Object {id: "O003"}) MERGE (e3)-[:TRIGGERED {method: "voice"}]->(o3)
MATCH (e4:Event {id: "E004"}), (o4:Object {id: "O004"}) MERGE (e4)-[:TRIGGERED {method: "camera"}]->(o4)
MATCH (e5:Event {id: "E005"}), (o5:Object {id: "O005"}) MERGE (e5)-[:TRIGGERED {method: "sensor"}]->(o5)

// LEADS_TO 关系 (Object -> Knowledge)
MATCH (o1:Object {id: "O001"}), (k1:Knowledge {id: "K001"}) MERGE (o1)-[:LEADS_TO {relevance: 0.99}]->(k1)
MATCH (o2:Object {id: "O002"}), (k2:Knowledge {id: "K002"}) MERGE (o2)-[:LEADS_TO {relevance: 0.95}]->(k2)
MATCH (o3:Object {id: "O003"}), (k3:Knowledge {id: "K003"}) MERGE (o3)-[:LEADS_TO {relevance: 0.97}]->(k3)
MATCH (o4:Object {id: "O004"}), (k4:Knowledge {id: "K004"}) MERGE (o4)-[:LEADS_TO {relevance: 0.96}]->(k4)
MATCH (o5:Object {id: "O005"}), (k5:Knowledge {id: "K005"}) MERGE (o5)-[:LEADS_TO {relevance: 0.98}]->(k5)
"""

def initialize_database():
    print(f"正在准备连接 Neo4j 数据库... ({NEO4J_URI})")
    try:
        driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
        with driver.session() as session:
            # 1. 清理数据库 (防止脏数据)
            print("正在清理数据库中原有的数据...")
            session.run("MATCH (n) DETACH DELETE n")
            
            # 2. 写入节点
            print("正在批量注入 5 类实体（共 50 个节点）...")
            session.run(CYPHER_CREATE_NODES)
            
            # 3. 写入关系
            print("正在批量建立实体间业务链条关系（共 20 组核心关系）...")
            session.run(CYPHER_CREATE_RELATIONSHIPS)
            
            print("🎉 KidoAI 知识图谱初始化成功！已成功创建 50 个实体节点并建立深度关系链。")
        driver.close()
    except Exception as e:
        print(f"❌ 数据库初始化失败，请确认 Neo4j 服务是否启动：{e}")

if __name__ == "__main__":
    initialize_database()
