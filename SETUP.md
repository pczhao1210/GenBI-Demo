# GenBI 安装配置指南

## 环境要求

- Python 3.8+
- pip

## 安装步骤

### 1. 克隆项目

```bash
git clone https://github.com/pczhao1210/GenBI-Demo.git
cd GenBI-Demo
```

### 2. 创建虚拟环境

```bash
python -m venv .venv
source .venv/bin/activate  # Linux/Mac
# 或
.venv\Scripts\activate     # Windows
```

### 3. 安装依赖

```bash
pip install -r requirements.txt
```

### 4. 配置文件设置

#### LLM配置
复制示例配置文件并修改：
```bash
cp config/example_llm_config.json config/llm_config.json
```

编辑 `config/llm_config.json`，填入您的API密钥和配置。

#### 数据库配置
```bash
cp config/example_database_config.json config/database_config.json
```

编辑 `config/database_config.json`，填入您的数据库连接信息。

### 5. 启动应用

#### 快速启动（推荐）
```bash
./start.sh
```

#### 手动启动

##### 启动后端API（可选）
```bash
cd backend
uvicorn main:app --reload --port 8000
```

##### 启动前端应用
```bash
streamlit run app.py --server.port 8501
```

### 6. 访问应用

- 前端界面: http://localhost:8501
- API文档: http://localhost:8000/docs（如果启动了后端）

## 配置说明

### LLM提供商支持
- OpenAI
- Azure OpenAI
- 自定义API（兼容OpenAI格式）

### 数据库支持
- MySQL
- AWS Athena

## 使用流程

1. 配置LLM服务
2. 配置数据库连接
3. 设置数据库Schema
4. 开始智能查询和分析

## 注意事项

- 请妥善保管API密钥，不要提交到版本控制
- 首次使用需要在Schema配置页面设置表结构
- 建议启用"避免执行危险代码"选项确保数据安全