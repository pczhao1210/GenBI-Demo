import streamlit as st
import json
import os
import time
from utils.config_manager import ConfigManager
from utils.llm_client import LLMClient
from utils.i18n import t, language_selector

st.set_page_config(page_title="LLM Configuration", page_icon="🤖")
st.title(f"🤖 {t('llm_config')}")

# 全局语言支持 - 不需要在子页面显示选择器

config_manager = ConfigManager()

# 加载现有配置
llm_config = config_manager.load_llm_config()

# LLM提供商选择
provider = st.selectbox(
    t('select_provider'),
    ["openai", "azure_openai", "custom"],
    index=["openai", "azure_openai", "custom"].index(llm_config.get("provider", "openai"))
)

st.subheader(t('config_params'))

if provider == "openai":
    st.markdown(f"### {t('openai_config')}")
    api_key = st.text_input("API Key", value=llm_config.get("openai", {}).get("api_key", ""), type="password")
    base_url = st.text_input("Base URL", value=llm_config.get("openai", {}).get("base_url", "https://api.openai.com/v1"))
    # 获取当前模型
    current_model = llm_config.get("openai", {}).get("model", "gpt-4")
    model_options = ["gpt-4", "gpt-3.5-turbo", "gpt-4-turbo", "gpt-4o", "gpt-4o-mini"]
    
    # 兼容性处理：如果当前模型不在选项中，添加到列表并显示警告
    if current_model not in model_options:
        model_options.append(current_model)
        st.warning(f"⚠️ 当前配置的模型 '{current_model}' 可能不是标准模型，建议选择推荐的模型")
    
    # 确定选择索引
    model_index = model_options.index(current_model)
    
    model = st.selectbox(t('model'), model_options, index=model_index)
    organization = st.text_input("Organization", value=llm_config.get("openai", {}).get("organization", ""))

elif provider == "azure_openai":
    st.markdown(f"### {t('azure_openai_config')}")
    api_key = st.text_input("API Key", value=llm_config.get("azure_openai", {}).get("api_key", ""), type="password")
    endpoint = st.text_input("Endpoint", value=llm_config.get("azure_openai", {}).get("endpoint", ""))
    api_version = st.text_input("API Version", value=llm_config.get("azure_openai", {}).get("api_version", "2024-02-01"))
    deployment_name = st.text_input("Deployment Name", value=llm_config.get("azure_openai", {}).get("deployment_name", ""))

else:  # custom
    st.markdown(f"### {t('custom_config')}")
    base_url = st.text_input("Base URL", value=llm_config.get("custom", {}).get("base_url", "http://localhost:11434/v1"))
    api_key = st.text_input("API Key", value=llm_config.get("custom", {}).get("api_key", "ollama"), type="password")
    model = st.text_input(t('model_name'), value=llm_config.get("custom", {}).get("model", "llama2"))

# 模型参数
st.markdown(f"### {t('model_params')}")
col1, col2 = st.columns(2)
with col1:
    temperature = st.slider("Temperature", 0.0, 2.0, llm_config.get("parameters", {}).get("temperature", 0.7), 0.1)
with col2:
    max_tokens = st.number_input("Max Tokens", 1, 8000, llm_config.get("parameters", {}).get("max_tokens", 4000))

# 按钮操作
col1, col2 = st.columns(2)
with col1:
    if st.button(t('test_connection'), type="secondary"):
        with st.spinner(t('testing_connection')):
            # 创建临时配置进行测试
            test_config = {
                "provider": provider,
                "parameters": {
                    "temperature": temperature,
                    "max_tokens": max_tokens
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
                    st.success(f"{t('connection_test_success')} {t('response_time')}: {elapsed_time:.2f}s")
                    st.info(t('model_response'))
                    st.text_area(t('response_content'), value=response, height=150, disabled=True, label_visibility="collapsed")
                else:
                    st.warning(t('connection_success_unexpected'))
                    st.text_area(t('response_content'), value=response, height=150, disabled=True, label_visibility="collapsed")
            except Exception as e:
                st.error(f"{t('connection_test_failed')}: {str(e)}")
                st.info(t('check_config'))

with col2:
    if st.button(t('save_config'), type="primary"):
        new_config = {
            "provider": provider,
            "parameters": {
                "temperature": temperature,
                "max_tokens": max_tokens
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
        st.success(t('config_saved'))