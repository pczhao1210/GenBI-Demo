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
        """加载测试问题"""
        return {
            "时间维度分析": [
                (1, "哪个季节的销售额最高？季节性趋势是什么？"),
                (2, "月度销售增长率如何？哪些月份表现异常？"),
                (3, "工作日vs周末的销售模式有什么差异？"),
                (4, "2020-2025年期间，年度销售复合增长率是多少？"),
                (5, "节假日对销售的影响程度如何？"),
            ],
            "产品维度分析": [
                (6, "哪些产品是畅销品？哪些是滞销品？"),
                (7, "不同产品类别的利润率排名如何？"),
                (8, "产品生命周期各阶段的销售特征是什么？"),
                (9, "哪些产品组合经常一起购买？"),
                (10, "产品价格敏感性分析：涨价对销量的影响？"),
            ],
            "客户价值分析": [
                (11, "客户的RFM分析结果如何？（最近消费、频率、金额）"),
                (12, "高价值客户的特征和行为模式是什么？"),
                (13, "客户流失预警：哪些客户有流失风险？"),
                (14, "新客户获取成本vs老客户维护成本对比？"),
                (15, "不同客户群体的平均订单价值差异？"),
            ],
            "地域分析": [
                (16, "哪些地区的市场渗透率最高？"),
                (17, "不同国家/城市的消费偏好有什么差异？"),
                (18, "地域扩张的优先级排序依据是什么？"),
                (19, "运输距离对订单成本和客户满意度的影响？"),
                (20, "各地区的市场饱和度如何？"),
            ],
            "库存管理分析": [
                (21, "库存周转率最高和最低的产品分别是哪些？"),
                (22, "缺货频率最高的产品及其影响？"),
                (23, "安全库存设置是否合理？过量库存成本多少？"),
                (24, "供应商交货及时性如何？哪家供应商最可靠？"),
                (25, "Lead Time对库存成本的影响分析？"),
            ],
            "员工绩效分析": [
                (26, "销售员工的业绩排名及差异原因？"),
                (27, "员工的客户维护能力如何评估？"),
                (28, "不同员工负责的客户群体有什么特征？"),
                (29, "员工培训投入与业绩提升的相关性？"),
                (30, "团队协作对整体销售的影响？"),
            ],
            "盈利能力分析": [
                (31, "毛利率最高的产品类别和客户群体？"),
                (32, "运输成本占总成本的比例及优化空间？"),
                (33, "不同销售渠道的投资回报率对比？"),
                (34, "应收账款周转情况及信用风险评估？"),
                (35, "折扣策略对整体利润的影响？"),
            ],
            "成本控制分析": [
                (36, "单位获客成本趋势及优化建议？"),
                (37, "物流成本vs销售额的比例变化？"),
                (38, "哪些环节的成本控制效果最明显？"),
                (39, "供应商价格波动对成本的影响？"),
                (40, "规模经济效应在哪些方面体现最明显？"),
            ],
            "竞争分析": [
                (41, "市场份额变化趋势及竞争态势？"),
                (42, "价格竞争力分析：我们的定价策略如何？"),
                (43, "产品差异化程度及竞争优势？"),
                (44, "客户忠诚度与竞争对手比较？"),
                (45, "新产品上市成功率及市场接受度？"),
            ],
            "趋势预测": [
                (46, "基于历史数据，下季度销售预测？"),
                (47, "哪些产品需要提前备货？数量多少？"),
                (48, "客户需求变化趋势及应对策略？"),
                (49, "新兴市场的增长潜力评估？"),
                (50, "供应链中断风险及应急预案？"),
            ],
            "服务质量": [
                (51, "订单处理时效性统计及改进点？"),
                (52, "客户投诉率及主要问题分类？"),
                (53, "退货率最高的产品及原因分析？"),
                (54, "供应商质量评估及改进建议？"),
                (55, "客户满意度调查结果及提升措施？"),
            ],
            "流程优化": [
                (56, "订单-交付周期的瓶颈在哪里？"),
                (57, "库存补货频率优化建议？"),
                (58, "跨部门协作效率评估？"),
                (59, "信息系统使用效率及改进空间？"),
                (60, "业务流程自动化的投资回报分析？"),
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
            "简单": ["时间维度分析", "产品维度分析"],
            "中等": ["客户价值分析", "地域分析", "库存管理分析", "员工绩效分析"],
            "困难": ["盈利能力分析", "成本控制分析", "竞争分析", "趋势预测", "服务质量", "流程优化"]
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