import streamlit as st
import json
import os
import time
from utils.config_manager import ConfigManager
from utils.llm_client import LLMClient

st.set_page_config(page_title="LLM配置", page_icon="🤖")
st.title("🤖 LLM配置")

config_manager = ConfigManager()

# 加载现有配置
llm_config = config_manager.load_llm_config()

# LLM提供商选择
provider = st.selectbox(
    "选择LLM提供商",
    ["openai", "azure_openai", "custom"],
    index=["openai", "azure_openai", "custom"].index(llm_config.get("provider", "openai"))
)

st.subheader("配置参数")

if provider == "openai":
    st.markdown("### OpenAI配置")
    api_key = st.text_input("API Key", value=llm_config.get("openai", {}).get("api_key", ""), type="password")
    base_url = st.text_input("Base URL", value=llm_config.get("openai", {}).get("base_url", "https://api.openai.com/v1"))
    # 获取当前模型
    current_model = llm_config.get("openai", {}).get("model", "gpt-4")
    model_options = ["gpt-4", "gpt-3.5-turbo", "gpt-4-turbo"]
    
    # 确定选择索引
    try:
        model_index = model_options.index(current_model)
    except ValueError:
        model_index = 0
    
    model = st.selectbox("模型", model_options, index=model_index)
    organization = st.text_input("Organization", value=llm_config.get("openai", {}).get("organization", ""))

elif provider == "azure_openai":
    st.markdown("### Azure OpenAI配置")
    api_key = st.text_input("API Key", value=llm_config.get("azure_openai", {}).get("api_key", ""), type="password")
    endpoint = st.text_input("Endpoint", value=llm_config.get("azure_openai", {}).get("endpoint", ""))
    api_version = st.text_input("API Version", value=llm_config.get("azure_openai", {}).get("api_version", "2024-02-01"))
    deployment_name = st.text_input("Deployment Name", value=llm_config.get("azure_openai", {}).get("deployment_name", ""))

else:  # custom
    st.markdown("### 自定义配置")
    base_url = st.text_input("Base URL", value=llm_config.get("custom", {}).get("base_url", "http://localhost:11434/v1"))
    api_key = st.text_input("API Key", value=llm_config.get("custom", {}).get("api_key", "ollama"), type="password")
    model = st.text_input("模型名称", value=llm_config.get("custom", {}).get("model", "llama2"))

# 模型参数
st.markdown("### 模型参数")
col1, col2, col3 = st.columns(3)
with col1:
    temperature = st.slider("Temperature", 0.0, 2.0, llm_config.get("parameters", {}).get("temperature", 0.7), 0.1)
with col2:
    max_tokens = st.number_input("Max Tokens", 1, 8000, llm_config.get("parameters", {}).get("max_tokens", 4000))
with col3:
    top_p = st.slider("Top P", 0.0, 1.0, llm_config.get("parameters", {}).get("top_p", 0.9), 0.1)

# 按钮操作
col1, col2 = st.columns(2)
with col1:
    if st.button("测试连接", type="secondary"):
        with st.spinner("测试连接中..."):
            # 创建临时配置进行测试
            test_config = {
                "provider": provider,
                "parameters": {
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                    "top_p": top_p
                }
            }
            
            # 根据提供商添加相应配置
            if provider == "openai":
                test_config["openai"] = {
                    "api_key": api_key,
                    "base_url": base_url,
                    "model": model,
                    "organization": organization
                }
            elif provider == "azure_openai":
                test_config["azure_openai"] = {
                    "api_key": api_key,
                    "endpoint": endpoint,
                    "api_version": api_version,
                    "deployment_name": deployment_name
                }
            else:  # custom
                test_config["custom"] = {
                    "base_url": base_url,
                    "api_key": api_key,
                    "model": model
                }
            
            # 创建LLM客户端
            llm_client = LLMClient(test_config)
            
            # 准备测试提示
            test_prompt = """请回答一个简单的问题来测试连接。回答中请包含“连接测试成功”这几个字。"""
            
            try:
                # 记录开始时间
                start_time = time.time()
                
                # 调用LLM API
                response = llm_client.generate_sql(test_prompt)
                
                # 计算响应时间
                elapsed_time = time.time() - start_time
                
                if response and "连接测试成功" in response:
                    st.success(f"连接测试成功！响应时间: {elapsed_time:.2f}秒")
                    st.info("模型响应:")
                    st.text_area("响应内容", value=response, height=150, disabled=True, label_visibility="collapsed")
                else:
                    st.warning("连接成功，但模型响应不符合预期")
                    st.text_area("响应内容", value=response, height=150, disabled=True, label_visibility="collapsed")
            except Exception as e:
                st.error(f"连接测试失败: {str(e)}")
                st.info("请检查您的配置参数并重试")

with col2:
    if st.button("保存配置", type="primary"):
        new_config = {
            "provider": provider,
            "parameters": {
                "temperature": temperature,
                "max_tokens": max_tokens,
                "top_p": top_p
            }
        }
        
        if provider == "openai":
            new_config["openai"] = {
                "api_key": api_key,
                "base_url": base_url,
                "model": model,
                "organization": organization
            }
        elif provider == "azure_openai":
            new_config["azure_openai"] = {
                "api_key": api_key,
                "endpoint": endpoint,
                "api_version": api_version,
                "deployment_name": deployment_name
            }
        else:  # custom
            new_config["custom"] = {
                "base_url": base_url,
                "api_key": api_key,
                "model": model
            }
        
        config_manager.save_llm_config(new_config)
        st.success("配置已保存！")