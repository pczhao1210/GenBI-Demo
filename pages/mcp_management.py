import streamlit as st
from utils.config_manager import ConfigManager

st.set_page_config(page_title="MCP管理", page_icon="🔧")
st.title("🔧 MCP工具管理")

config_manager = ConfigManager()
mcp_config = config_manager.load_mcp_config()

# 添加新的MCP Server
st.subheader("添加MCP Server")
with st.expander("新增服务器"):
    name = st.text_input("服务器名称")
    server_type = st.selectbox("类型", ["stdio", "sse"])
    
    if server_type == "stdio":
        command = st.text_input("命令", value="python")
        args = st.text_input("参数", value="mcp_server.py")
    else:
        url = st.text_input("URL", value="http://localhost:8001/mcp")
    
    if st.button("添加服务器"):
        if name:
            new_server = {
                "type": server_type,
                "status": "inactive"
            }
            if server_type == "stdio":
                new_server.update({"command": command, "args": args.split()})
            else:
                new_server["url"] = url
            
            mcp_config[name] = new_server
            config_manager.save_mcp_config(mcp_config)
            st.success(f"服务器 {name} 已添加")
            st.rerun()

# MCP Server列表
st.subheader("MCP Server列表")

if not mcp_config:
    st.info("暂无MCP服务器，请添加新的服务器")
else:
    for name, config in mcp_config.items():
        with st.container():
            col1, col2, col3, col4 = st.columns([2, 1, 1, 2])
            
            with col1:
                status_icon = "🟢" if config.get("status") == "active" else "🔴"
                st.write(f"{status_icon} **{name}**")
                st.caption(f"类型: {config.get('type', 'unknown')}")
            
            with col2:
                if st.button("启动", key=f"start_{name}"):
                    mcp_config[name]["status"] = "active"
                    config_manager.save_mcp_config(mcp_config)
                    st.success(f"{name} 已启动")
                    st.rerun()
            
            with col3:
                if st.button("停止", key=f"stop_{name}"):
                    mcp_config[name]["status"] = "inactive"
                    config_manager.save_mcp_config(mcp_config)
                    st.success(f"{name} 已停止")
                    st.rerun()
            
            with col4:
                if st.button("删除", key=f"delete_{name}"):
                    del mcp_config[name]
                    config_manager.save_mcp_config(mcp_config)
                    st.success(f"{name} 已删除")
                    st.rerun()
            
            st.divider()