import streamlit as st
from utils.config_manager import ConfigManager
from utils.i18n import t
from utils.mcp_client import MCPClient
import shlex

st.set_page_config(page_title="MCP Management", page_icon="🔧")
st.title(t('mcp_tool_management'))
st.info("本页启用/禁用按需 stdio 调用，不启动常驻服务。当前支持内置换行 JSON RPC，不支持 SSE 或完整 MCP 握手。")

config_manager = ConfigManager()
mcp_client = MCPClient()
mcp_config = config_manager.load_mcp_config()

# 添加刷新按钮来动态发现服务器
col1, col2 = st.columns([3, 1])
with col1:
    st.subheader("MCP服务器管理")
with col2:
    if st.button("🔄 发现服务器", help="扫描并更新可用的MCP服务器"):
        # 发现可用服务器
        discovered_servers = mcp_client.discover_available_servers()
        
        # 更新配置
        for server_name, server_info in discovered_servers.items():
            if server_name not in mcp_config:
                mcp_config[server_name] = {
                    "type": "stdio",
                    "command": "python",
                    "args": [f"mcp_servers/{server_name}_server.py"],
                    "status": "inactive",
                    "description": server_info.get("description", ""),
                    "capabilities": server_info.get("capabilities", []),
                    "version": server_info.get("version", "1.0.0"),
                    "methods": server_info.get("methods", [])
                }
        
        config_manager.save_mcp_config(mcp_config)
        st.success("服务器发现完成！")
        st.rerun()

# 添加新的MCP Server
st.subheader(t('add_mcp_server'))
with st.expander(t('new_server')):
    name = st.text_input(t('server_name'))
    server_type = st.selectbox(t('type'), ["stdio"])
    
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
                try:
                    parsed_args = shlex.split(args)
                except ValueError as exc:
                    st.error(str(exc))
                    st.stop()
                new_server.update({"command": command, "args": parsed_args})
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
            col1, col2, col3, col4 = st.columns([3, 1, 1, 1])
            
            with col1:
                status_icon = "🟢" if config.get("status") == "active" else "🔴"
                st.write(f"{status_icon} **{name}**")
                
                # 显示服务器类型和描述
                server_type = config.get('type', 'unknown')
                description = config.get('description', '无描述')
                st.caption(f"**类型**: {server_type}")
                st.caption(f"**描述**: {description}")
                
                # 显示命令信息（如果是stdio类型）
                if server_type == "stdio":
                    command = config.get('command', 'unknown')
                    args = config.get('args', [])
                    if args:
                        st.caption(f"**命令**: {command} {' '.join(args)}")
                    else:
                        st.caption(f"**命令**: {command}")
                elif server_type == "sse":
                    url = config.get('url', 'unknown')
                    st.caption(f"**URL**: {url}")
                
                # 显示功能列表
                capabilities = config.get('capabilities', [])
                if capabilities:
                    st.caption(f"**功能**: {', '.join(capabilities)}")
                
                # 显示版本和方法信息
                version = config.get('version')
                methods = config.get('methods', [])
                if version:
                    st.caption(f"**版本**: {version}")
                if methods:
                    st.caption(f"**方法**: {', '.join(methods)}")
                
                # 实时状态检查
                if st.button("🔍 检查状态", key=f"check_{name}"):
                    server_info = mcp_client.get_server_info(name)
                    if "error" not in server_info:
                        st.success(f"✅ {name} 脚本可响应；数据库连接需单独测试")
                        # 更新配置中的信息
                        mcp_config[name].update({
                            "description": server_info.get("description", config.get("description", "")),
                            "capabilities": (config.get("capabilities", {}) if config.get("protocol") == "mcp"
                                             else server_info.get("capabilities", [])),
                            "version": server_info.get("version", "1.0.0"),
                            "methods": server_info.get("methods", [])
                        })
                        config_manager.save_mcp_config(mcp_config)
                        st.rerun()
                    else:
                        st.error(f"❌ {name} 服务器检查失败: {server_info.get('error', '未知错误')}")
            
            with col2:
                if st.button(t('enable_on_demand'), key=f"start_{name}"):
                    mcp_config[name]["status"] = "active"
                    config_manager.save_mcp_config(mcp_config)
                    st.success(f"{name}: {t('enable_on_demand')}")
                    st.rerun()
            
            with col3:
                if st.button(t('disable_server'), key=f"stop_{name}"):
                    mcp_config[name]["status"] = "inactive"
                    config_manager.save_mcp_config(mcp_config)
                    st.success(f"{name}: {t('disable_server')}")
                    st.rerun()
            
            with col4:
                if st.button(t('delete'), key=f"delete_{name}"):
                    del mcp_config[name]
                    config_manager.save_mcp_config(mcp_config)
                    st.success(f"{name} {t('deleted')}")
                    st.rerun()
            
            st.divider()

with st.expander(t("standard_mcp_config")):
    import json
    st.caption(t("standard_mcp_help"))
    settings = st.text_area(t("standard_mcp_json"), "{}")
    if st.button(t("save_standard_mcp")):
        try:
            servers = json.loads(settings)
            if not isinstance(servers, dict):
                raise ValueError("MCP configuration must be an object keyed by server name")
            for value in servers.values():
                if (value.get("protocol") != "mcp" or value.get("type") not in ("stdio", "streamable_http")
                        or not isinstance(value.get("capabilities", {}), dict)):
                    raise ValueError("Standard MCP requires protocol=mcp, stdio/streamable_http and capability mapping")
            config_manager.save_mcp_config({**mcp_config, **servers})
            st.success(t("config_saved"))
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))