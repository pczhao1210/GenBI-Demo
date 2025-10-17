import streamlit as st
import pandas as pd
from utils.config_manager import ConfigManager
from utils.mcp_client import MCPClient
from utils.i18n import t
import time

st.set_page_config(page_title="Enhanced Database Configuration", page_icon="🗄️")
st.title(f"🗄️ {t('database_config')} - 增强版")

config_manager = ConfigManager()
mcp_client = MCPClient()
db_config = config_manager.load_database_config()

# 添加tab界面
tab1, tab2, tab3 = st.tabs(["数据库配置", "连接状态", "性能监控"])

with tab1:
    st.subheader("数据库连接配置")
    
    # 数据库类型选择
    db_type = st.selectbox("选择数据库类型", ["mysql", "athena"])

    if db_type == "mysql":
        st.subheader("MySQL 配置")
        
        col1, col2 = st.columns(2)
        with col1:
            host = st.text_input("主机地址", value=db_config.get("mysql", {}).get("host", "localhost"))
            database = st.text_input("数据库名", value=db_config.get("mysql", {}).get("database", ""))
            username = st.text_input("用户名", value=db_config.get("mysql", {}).get("username", ""))
            
        with col2:
            port = st.number_input("端口", min_value=1, max_value=65535, value=db_config.get("mysql", {}).get("port", 3306))
            password = st.text_input("密码", value=db_config.get("mysql", {}).get("password", ""), type="password")
            
        st.subheader("高级设置")
        col3, col4 = st.columns(2)
        with col3:
            max_rows = st.number_input("最大返回行数", min_value=1, max_value=10000, value=db_config.get("mysql", {}).get("max_rows", 1000))
            connection_timeout = st.number_input("连接超时(秒)", min_value=1, max_value=60, value=db_config.get("mysql", {}).get("connection_timeout", 10))
        with col4:
            max_connections = st.number_input("最大连接数", min_value=1, max_value=20, value=db_config.get("mysql", {}).get("max_connections", 5))
            query_timeout = st.number_input("查询超时(秒)", min_value=1, max_value=300, value=db_config.get("mysql", {}).get("query_timeout", 30))
        
        # SSL设置
        st.subheader("🔒 SSL安全连接设置")
        
        # 添加SSL信息提示
        with st.expander("ℹ️ SSL连接说明", expanded=False):
            st.markdown("""
            **常见SSL错误及解决方案：**
            
            🚨 **错误**: `Connections using insecure transport are prohibited while --require_secure_transport=ON`
            
            **解决方案**：
            1. ✅ 启用"系统CA证书"或"强制SSL连接"选项
            2. 🔧 或者联系数据库管理员关闭 `require_secure_transport`
            
            **SSL模式说明**：
            - **禁用SSL**: 不使用SSL连接（适用于本地开发）
            - **系统CA证书**: 使用SSL并通过系统CA证书验证服务器（推荐，安全简便）
            - **自定义证书**: 使用SSL并验证自定义证书文件（高级配置）
            - **强制SSL**: 使用SSL但不验证证书（适用于需要SSL但无证书）
            """)
        
        # 兼容旧配置
        ssl_options = ["禁用SSL", "系统CA证书", "自定义证书", "强制SSL"]
        current_ssl_mode = db_config.get("mysql", {}).get("ssl_mode", "系统CA证书")
        
        # 将旧的"验证证书"选项映射到新的"自定义证书"
        if current_ssl_mode == "验证证书":
            current_ssl_mode = "自定义证书"
        
        # 确保值在有效选项中
        if current_ssl_mode not in ssl_options:
            current_ssl_mode = "系统CA证书"
        
        ssl_mode = st.selectbox(
            "SSL连接模式", 
            ssl_options,
            index=ssl_options.index(current_ssl_mode)
        )
        
        use_ssl = ssl_mode != "禁用SSL"
        verify_ssl = ssl_mode in ["系统CA证书", "自定义证书"]
        
        ssl_ca = ""
        ssl_cert = ""
        ssl_key = ""
        
        if ssl_mode == "自定义证书":
            st.markdown("**证书文件配置** （用于自定义证书模式）")
            ssl_ca = st.text_input("CA证书路径", value=db_config.get("mysql", {}).get("ssl_ca", ""), 
                                 help="服务器CA证书文件路径")
            ssl_cert = st.text_input("客户端证书路径", value=db_config.get("mysql", {}).get("ssl_cert", ""),
                                   help="客户端证书文件路径（可选）")
            ssl_key = st.text_input("客户端密钥路径", value=db_config.get("mysql", {}).get("ssl_key", ""),
                                  help="客户端私钥文件路径（可选）")
        elif ssl_mode == "系统CA证书":
            st.info("💡 **系统CA证书模式**：将使用操作系统的根证书存储来验证MySQL服务器证书，无需手动配置证书文件。")
    
    # 测试连接和保存配置
    col1, col2, col3 = st.columns(3)
    with col1:
        if st.button("🔍 测试连接", type="secondary"):
            with st.spinner("测试连接中..."):
                if db_type == "mysql":
                    test_config = {
                        "host": host,
                        "port": port,
                        "database": database,
                        "username": username,
                        "password": password,
                        "max_rows": max_rows,
                        "connection_timeout": connection_timeout,
                        "max_connections": max_connections,
                        "query_timeout": query_timeout,
                        "ssl_mode": ssl_mode,
                        "use_ssl": use_ssl,
                        "verify_ssl": verify_ssl
                    }
                    
                    # 添加SSL证书配置
                    if ssl_mode == "自定义证书":
                        test_config.update({
                            "ssl_ca": ssl_ca,
                            "ssl_cert": ssl_cert,
                            "ssl_key": ssl_key
                        })
                
                # 测试基本连接
                start_time = time.time()
                tables_result = mcp_client.call_mcp_server_with_config(
                    db_type, 
                    "get_tables", 
                    test_config
                )
                connection_time = time.time() - start_time
                
                if "error" in tables_result:
                    st.error(f"❌ 连接失败: {tables_result['error']}")
                else:
                    result_data = tables_result.get("result", {})
                    if result_data.get("success"):
                        tables = result_data.get("tables", [])
                        if isinstance(tables, list) and len(tables) > 0 and isinstance(tables[0], dict):
                            # 新版本返回详细表信息
                            table_count = len(tables)
                            total_rows = sum(t.get("estimated_rows", 0) for t in tables)
                            st.success(f"✅ 连接成功!")
                            
                            # 显示连接信息
                            col_a, col_b, col_c = st.columns(3)
                            with col_a:
                                st.metric("连接时间", f"{connection_time:.2f}秒")
                            with col_b:
                                st.metric("表数量", table_count)
                            with col_c:
                                st.metric("预估总行数", f"{total_rows:,}")
                            
                            # 显示表信息
                            if tables:
                                st.subheader("数据库表信息")
                                df = pd.DataFrame(tables)
                                st.dataframe(df, width='stretch')
                        else:
                            # 兼容旧版本
                            table_count = len(tables) if isinstance(tables, list) else 0
                            st.success(f"✅ 连接成功! 发现 {table_count} 个表")
                    else:
                        st.error(f"❌ 获取表信息失败")
    
    with col2:
        if st.button("💾 保存配置", type="primary"):
            if db_type == "mysql":
                save_config = {
                    "host": host,
                    "port": port,
                    "database": database,
                    "username": username,
                    "password": password,
                    "max_rows": max_rows,
                    "connection_timeout": connection_timeout,
                    "max_connections": max_connections,
                    "query_timeout": query_timeout,
                    "ssl_mode": ssl_mode,
                    "use_ssl": use_ssl,
                    "verify_ssl": verify_ssl
                }
                
                # 添加SSL证书配置（仅在自定义证书模式下）
                if ssl_mode == "自定义证书":
                    save_config.update({
                        "ssl_ca": ssl_ca,
                        "ssl_cert": ssl_cert,
                        "ssl_key": ssl_key
                    })
            
            config_manager.save_database_config(db_type, save_config)
            st.success("✅ 配置已保存!")
            st.rerun()
    
    with col3:
        if st.button("🗑️ 清除配置"):
            config_manager.save_database_config(db_type, {})
            st.success("✅ 配置已清除!")
            st.rerun()

with tab2:
    st.subheader("数据库连接状态")
    
    if db_type in db_config and db_config[db_type]:
        current_config = db_config[db_type]
        
        # 显示当前配置
        st.subheader("当前配置")
        config_display = {}
        for key, value in current_config.items():
            if key == "password":
                config_display[key] = "***" if value else ""
            else:
                config_display[key] = value
        
        df_config = pd.DataFrame(list(config_display.items()), columns=["配置项", "值"])
        st.dataframe(df_config, width='stretch')
        
        # 实时连接测试
        if st.button("🔄 刷新连接状态"):
            with st.spinner("检查连接状态..."):
                # 获取数据库统计信息
                stats_result = mcp_client.call_mcp_server_with_config(
                    db_type,
                    "get_database_stats", 
                    current_config
                )
                
                if "error" not in stats_result and stats_result.get("result", {}).get("success"):
                    stats = stats_result["result"]["stats"]
                    
                    col1, col2, col3 = st.columns(3)
                    with col1:
                        st.metric("表数量", stats.get("table_count", 0))
                    with col2:
                        st.metric("总记录数", f"{stats.get('total_rows', 0):,}")
                    with col3:
                        st.metric("数据库大小", f"{stats.get('size_mb', 0)} MB")
                    
                    st.success("✅ 数据库连接正常")
                else:
                    error_msg = stats_result.get("error", "未知错误")
                    st.error(f"❌ 连接失败: {error_msg}")
    else:
        st.warning("⚠️ 尚未配置数据库连接")

with tab3:
    st.subheader("性能监控")
    
    if db_type in db_config and db_config[db_type]:
        st.info("🚧 性能监控功能开发中...")
        st.markdown("""
        **计划中的功能:**
        - 查询执行时间统计
        - 慢查询分析
        - 连接池状态监控
        - 错误统计和分析
        - 查询频率统计
        """)
        
        # 模拟一些性能数据
        st.subheader("模拟性能数据")
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("平均查询时间", "1.2秒", "0.1秒")
        with col2:
            st.metric("成功率", "98.5%", "1.2%")
        with col3:
            st.metric("活跃连接", "3/5", "1")
        with col4:
            st.metric("慢查询数", "2", "-1")
    else:
        st.warning("⚠️ 请先配置数据库连接")