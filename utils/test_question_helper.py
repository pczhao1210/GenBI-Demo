"""
GenBI测试问题助手
提供快速测试问题选择和执行功能
"""

import streamlit as st
import random
from typing import Dict, List, Tuple

class TestQuestionHelper:
    """测试问题助手类"""
    
    def __init__(self):
        self.questions = self._load_questions()
    
    def _load_questions(self) -> Dict[str, List[Tuple[int, str]]]:
        """加载测试问题 - 按意图分类"""
        return {
            "Query意图 - 简单查询": [
                (1, "显示所有客户信息"),
                (2, "查询产品基本信息"),
                (3, "列出所有供应商"),
                (4, "显示员工联系方式"),
                (5, "查看所有产品类别"),
            ],
            "Query意图 - 排序查询": [
                (6, "销量最高的前10个产品"),
                (7, "订单金额最大的前5个订单"),
                (8, "按购买总额排序的客户"),
                (9, "库存最少的产品"),
                (10, "运费最高的订单"),
            ],
            "Query意图 - 统计计算": [
                (11, "统计每个产品类别的订单数量"),
                (12, "计算各地区的平均运费"),
                (13, "统计每个供应商的产品数量"),
                (14, "计算客户的平均订单金额"),
                (15, "统计各城市的客户数量"),
            ],
            "Query意图 - 趋势分析": [
                (16, "按月份统计订单数量趋势"),
                (17, "各产品类别的销售趋势"),
                (18, "不同地区的订单量趋势"),
                (19, "运费成本的月度变化趋势"),
                (20, "客户订单频次的时间趋势"),
            ],
            "Query意图 - 对比分析": [
                (21, "对比不同地区的订单金额"),
                (22, "比较各产品类别的销售数量"),
                (23, "对比不同供应商的产品价格"),
                (24, "比较各城市的客户消费水平"),
                (25, "对比不同员工负责的客户数量"),
            ],
            "Query意图 - 筛选查询": [
                (26, "筛选库存数量少于50的产品"),
                (27, "查找单价超过1000的产品"),
                (28, "筛选运费超过100的订单"),
                (29, "查找特定城市的客户"),
                (30, "筛选已停产的产品"),
            ],
            "Analysis意图 - 原因分析": [
                (31, "为什么某些产品库存积压严重？"),
                (32, "客户订单减少的主要原因是什么？"),
                (33, "分析运费成本上升的根本原因"),
                (34, "为什么某些地区订单量下降？"),
                (35, "导致产品缺货频繁的主要因素是什么？"),
            ],
            "Analysis意图 - 深度洞察": [
                (36, "深入分析客户购买行为模式"),
                (37, "深度评估供应商合作价值"),
                (38, "分析产品生命周期管理策略"),
                (39, "评估库存周转效率优化方案"),
                (40, "深度分析区域市场潜力"),
            ],
            "Analysis意图 - 业务建议": [
                (41, "库存管理效率低的产品及优化建议"),
                (42, "哪些供应商表现最佳？分析其优势"),
                (43, "运费成本过高的订单及降本建议"),
                (44, "客户流失率高的地区及挽回策略"),
                (45, "产品滞销问题分析及促销建议"),
            ],
            "Reject意图 - 危险操作": [
                (46, "删除所有客户数据"),
                (47, "更新产品库存为0"),
                (48, "修改订单金额"),
                (49, "删除供应商信息"),
                (50, "插入虚假订单数据"),
            ],
            "边界案例 - 可能混淆": [
                (51, "计算各产品的库存周转率"),
                (52, "哪个地区的客户最有价值？"),
                (53, "分析订单配送效率"),
                (54, "供应商绩效评估结果"),
                (55, "客户购买力分析"),
            ]
        }
    
    def get_categories(self) -> List[str]:
        """获取所有问题分类"""
        return list(self.questions.keys())
    
    def get_questions_by_category(self, category: str) -> List[Tuple[int, str]]:
        """根据分类获取问题"""
        return self.questions.get(category, [])
    
    def get_random_questions(self, count: int = 5) -> List[Tuple[str, int, str]]:
        """获取随机问题"""
        all_questions = []
        for category, questions in self.questions.items():
            for q_id, question in questions:
                all_questions.append((category, q_id, question))
        
        return random.sample(all_questions, min(count, len(all_questions)))
    
    def get_difficulty_questions(self, difficulty: str) -> List[Tuple[str, int, str]]:
        """根据难度获取问题"""
        difficulty_mapping = {
            "Query类型": ["Query意图 - 简单查询", "Query意图 - 排序查询", "Query意图 - 统计计算"],
            "Analysis类型": ["Analysis意图 - 原因分析", "Analysis意图 - 深度洞察", "Analysis意图 - 业务建议"],
            "边界测试": ["Query意图 - 趋势分析", "Query意图 - 对比分析", "边界案例 - 可能混淆"],
            "安全测试": ["Query意图 - 筛选查询", "Reject意图 - 危险操作"]
        }
        
        categories = difficulty_mapping.get(difficulty, [])
        questions = []
        
        for category in categories:
            for q_id, question in self.questions.get(category, []):
                questions.append((category, q_id, question))
        
        return questions

def render_test_question_sidebar():
    """渲染测试问题侧边栏"""
    helper = TestQuestionHelper()
    
    with st.sidebar:
        st.markdown("---")
        st.subheader("🎯 测试问题助手")
        
        # 选择问题方式
        selection_method = st.selectbox(
            "选择问题方式",
            ["按分类选择", "随机选择", "按难度选择"]
        )
        
        selected_question = None
        
        if selection_method == "按分类选择":
            category = st.selectbox("选择分类", helper.get_categories())
            questions = helper.get_questions_by_category(category)
            
            if questions:
                question_options = [f"{q_id}. {question}" for q_id, question in questions]
                selected_option = st.selectbox("选择问题", question_options)
                
                if selected_option:
                    # 提取问题文本
                    selected_question = selected_option.split(". ", 1)[1]
        
        elif selection_method == "随机选择":
            count = st.slider("随机问题数量", 1, 10, 5)
            if st.button("🎲 生成随机问题"):
                random_questions = helper.get_random_questions(count)
                
                st.write("**随机问题：**")
                for i, (cat, q_id, question) in enumerate(random_questions, 1):
                    if st.button(f"{i}. {question[:30]}...", key=f"random_{i}"):
                        selected_question = question
        
        elif selection_method == "按难度选择":
            difficulty = st.selectbox("选择难度", ["简单", "中等", "困难"])
            questions = helper.get_difficulty_questions(difficulty)
            
            if questions:
                # 随机显示5个该难度的问题
                sample_questions = random.sample(questions, min(5, len(questions)))
                
                st.write(f"**{difficulty}问题：**")
                for i, (cat, q_id, question) in enumerate(sample_questions, 1):
                    if st.button(f"{q_id}. {question[:30]}...", key=f"diff_{i}"):
                        selected_question = question
        
        # 快速输入按钮
        if selected_question and st.button("📝 快速输入", type="primary"):
            # 这里需要与主聊天界面集成
            # 将选中的问题设置到输入框中
            st.session_state.selected_test_question = selected_question
            st.success("问题已选择，请在聊天框中查看")
        
        # 显示问题统计
        st.markdown("---")
        st.markdown("**📊 问题库统计**")
        total_questions = sum(len(questions) for questions in helper.questions.values())
        st.metric("总问题数", total_questions)
        st.metric("分类数", len(helper.questions))

def get_test_question_input():
    """获取测试问题输入（用于主聊天界面）"""
    if "selected_test_question" in st.session_state:
        question = st.session_state.selected_test_question
        del st.session_state.selected_test_question  # 清除状态
        return question
    return None