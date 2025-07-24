#!/bin/bash

# GenBI 一键启动脚本

echo "🚀 启动 GenBI 生成式BI查询系统..."

# 检查虚拟环境
if [ ! -d ".venv" ]; then
    echo "❌ 虚拟环境不存在，请先运行: python3 -m venv .venv"
    exit 1
fi

# 激活虚拟环境
echo "📦 激活虚拟环境..."
source .venv/bin/activate

# 安装依赖
echo "📥 安装依赖包..."
pip install -r requirements.txt

# 启动后端服务
echo "🔧 启动后端API服务..."
cd backend
uvicorn main:app --reload --port 8000 &
BACKEND_PID=$!
cd ..

# 等待后端启动
sleep 3

# 启动前端服务
echo "🎨 启动前端Streamlit应用..."
streamlit run app.py --server.port 8501 &
FRONTEND_PID=$!

echo ""
echo "✅ 服务启动完成！"
echo "📱 前端界面: http://localhost:8501"
echo "📚 API文档: http://localhost:8000/docs"
echo "❤️  API状态: http://localhost:8000/health"
echo ""
echo "按 Ctrl+C 停止所有服务"

# 等待用户中断
trap "echo '🛑 正在停止服务...'; kill $BACKEND_PID $FRONTEND_PID; exit" INT
wait