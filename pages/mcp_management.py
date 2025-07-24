import streamlit as st
from utils.config_manager import ConfigManager
from utils.i18n import t

st.set_page_config(page_title="MCP Management", page_icon="🔧")
st.title(t('mcp_tool_management'))

config_manager = ConfigManager()
mcp_config = config_manager.load_mcp_config()

# 添加新的MCP Server
st.subheader(t('add_mcp_server'))
with st.expander(t('new_server')):
    name = st.text_input(t('server_name'))
    server_type = st.selectbox(t('type'), ["stdio", "sse"])
    
    if server_type == "stdio":
        command = st.text_input(t('command'), value="python")
        args = st.text_input(t('parameters'), value="mcp_server.py")
    else:
        url = st.text_input("URL", value="http://localhost:8001/mcp")
    
    if st.button(t('add_server')):
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
            st.success(f"Server {name} added")
            st.rerun()

# MCP Server列表
st.subheader(t('mcp_server_list'))

if not mcp_config:
    st.info(t('no_mcp_servers'))
else:
    for name, config in mcp_config.items():
        with st.container():
            col1, col2, col3, col4 = st.columns([2, 1, 1, 2])
            
            with col1:
                status_icon = "🟢" if config.get("status") == "active" else "🔴"
                st.write(f"{status_icon} **{name}**")
                st.caption(f"{t('type')}: {config.get('type', 'unknown')}")
            
            with col2:
                if st.button(t('start'), key=f"start_{name}"):
                    mcp_config[name]["status"] = "active"
                    config_manager.save_mcp_config(mcp_config)
                    st.success(f"{name} {t('started')}")
                    st.rerun()
            
            with col3:
                if st.button(t('stop'), key=f"stop_{name}"):
                    mcp_config[name]["status"] = "inactive"
                    config_manager.save_mcp_config(mcp_config)
                    st.success(f"{name} {t('stopped')}")
                    st.rerun()
            
            with col4:
                if st.button(t('delete'), key=f"delete_{name}"):
                    del mcp_config[name]
                    config_manager.save_mcp_config(mcp_config)
                    st.success(f"{name} {t('deleted')}")
                    st.rerun()
            
            st.divider()