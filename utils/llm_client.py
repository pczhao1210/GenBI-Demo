import requests
import json
import openai
import time
from typing import Dict, Any, Optional, List, Union

# 辅助函数，用于处理嵌套字典的设置和获取
def nested_set(dic: Dict, keys: str, value: Any) -> None:
    """
    在嵌套字典中设置值
    例如: nested_set(data, "response.body.text", "hello")
    """
    keys = keys.split('.')
    for key in keys[:-1]:
        dic = dic.setdefault(key, {})
    dic[keys[-1]] = value

def nested_get(dic: Dict, keys: str) -> Any:
    """
    从嵌套字典中获取值
    例如: nested_get(data, "response.body.text")
    """
    keys = keys.split('.')
    for key in keys:
        if isinstance(dic, dict) and key in dic:
            dic = dic[key]
        else:
            return None
    return dic

class LLMClient:
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        
        # 如果配置是嵌套的，提取实际配置
        if "llm_config" in self.config:
            self.config = self.config["llm_config"]
            
        self.provider = self.config.get("provider", "openai")
    
    def generate_sql(self, prompt: str) -> Optional[str]:
        """根据提示生成SQL查询"""
        if self.provider == "openai":
            return self._call_openai(prompt)
        elif self.provider == "azure_openai":
            return self._call_azure_openai(prompt)
        elif self.provider == "custom":
            return self._call_custom(prompt)
        elif self.provider == "openai_sdk":
            return self._call_openai_sdk(prompt)
        return None
        
    def _call_openai_sdk(self, prompt: str) -> Optional[str]:
        """使用OpenAI SDK调用API"""
        try:
            openai_config = self.config.get("openai", {})
            params = self.config.get("parameters", {})
            
            # 设置OpenAI SDK的配置
            openai.api_key = openai_config.get("api_key")
            if openai_config.get("organization"):
                openai.organization = openai_config.get("organization")
            if openai_config.get("base_url"):
                openai.base_url = openai_config.get("base_url")
                
            # 调用API
            response = openai.chat.completions.create(
                model=openai_config.get("model", "gpt-3.5-turbo"),
                messages=[{"role": "user", "content": prompt}],
                temperature=params.get("temperature", 0.7),
                max_tokens=params.get("max_tokens", 4000),
                top_p=params.get("top_p", 0.9)
            )
            
            return response.choices[0].message.content.strip()
        except Exception as e:
            print(f"使用OpenAI SDK调用API时出错: {str(e)}")
            return None
    
    def _call_openai(self, prompt: str) -> Optional[str]:
        """调用OpenAI API"""
        try:
            openai_config = self.config.get("openai", {})
            params = self.config.get("parameters", {})
            
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {openai_config.get('api_key')}"
            }
            
            if openai_config.get("organization"):
                headers["OpenAI-Organization"] = openai_config.get("organization")
            
            data = {
                "model": openai_config.get("model", "gpt-3.5-turbo"),
                "messages": [{"role": "user", "content": prompt}],
                "temperature": params.get("temperature", 0.7),
                "max_tokens": params.get("max_tokens", 4000),
                "top_p": params.get("top_p", 0.9)
            }
            
            response = requests.post(
                f"{openai_config.get('base_url', 'https://api.openai.com/v1')}/chat/completions",
                headers=headers,
                json=data
            )
            
            if response.status_code == 200:
                result = response.json()
                return result["choices"][0]["message"]["content"].strip()
            else:
                print(f"OpenAI API错误: {response.status_code} - {response.text}")
                return None
        except Exception as e:
            print(f"调用OpenAI API时出错: {str(e)}")
            return None
    
    def _call_azure_openai(self, prompt: str) -> Optional[str]:
        """调用Azure OpenAI API"""
        try:
            azure_config = self.config.get("azure_openai", {})
            params = self.config.get("parameters", {})
            
            headers = {
                "Content-Type": "application/json",
                "api-key": azure_config.get("api_key")
            }
            
            data = {
                "messages": [{"role": "user", "content": prompt}],
                "temperature": params.get("temperature", 0.7),
                "max_tokens": params.get("max_tokens", 4000),
                "top_p": params.get("top_p", 0.9)
            }
            
            endpoint = azure_config.get("endpoint", "").rstrip("/")
            deployment = azure_config.get("deployment_name")
            api_version = azure_config.get("api_version", "2024-02-01")
            
            url = f"{endpoint}/openai/deployments/{deployment}/chat/completions?api-version={api_version}"
            
            response = requests.post(url, headers=headers, json=data)
            
            if response.status_code == 200:
                result = response.json()
                return result["choices"][0]["message"]["content"].strip()
            else:
                print(f"Azure OpenAI API错误: {response.status_code} - {response.text}")
                return None
        except Exception as e:
            print(f"调用Azure OpenAI API时出错: {str(e)}")
            return None
    
    def _call_custom(self, prompt: str) -> Optional[str]:
        """调用自定义LLM API"""
        try:
            custom_config = self.config.get("custom", {})
            params = self.config.get("parameters", {})
            
            # 获取API密钥和基础URL
            api_key = custom_config.get("api_key")
            model = custom_config.get("model", "llama2")
            
            # 直接使用原始的requests进行调用，确保使用POST方法
            headers = {
                "Content-Type": "application/json"
            }
            
            # 根据配置添加认证头
            auth_type = custom_config.get("auth_type", "bearer")
            if auth_type.lower() == "bearer" and api_key:
                headers["Authorization"] = f"Bearer {api_key}"
            elif auth_type.lower() == "api_key" and api_key:
                headers[custom_config.get("auth_header", "X-API-Key")] = api_key
            
            # 使用配置中的请求格式
            request_format = custom_config.get("request_format", "openai")
            
            if request_format == "openai":
                data = {
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": params.get("temperature", 0.7),
                    "max_tokens": params.get("max_tokens", 4000),
                    "top_p": params.get("top_p", 0.9)
                }
            else:
                # 自定义请求格式
                data = custom_config.get("request_template", {})
                # 将提示插入到模板中
                if "prompt_field" in custom_config:
                    nested_set(data, custom_config.get("prompt_field"), prompt)
                else:
                    # 默认将提示放在根级别的"prompt"字段
                    data["prompt"] = prompt
                
                # 添加参数
                for param_name, param_path in custom_config.get("param_mapping", {}).items():
                    if param_name in params:
                        nested_set(data, param_path, params[param_name])
            
            # 添加额外的请求参数
            for key, value in custom_config.get("additional_params", {}).items():
                if key not in data:
                    data[key] = value
            
            # 使用配置中的URL
            api_url = custom_config.get("base_url", custom_config.get("api_url", "http://oneapi.thingsbud.com/v1/chat/completions"))
            
            print(f"Direct POST request to: {api_url}")
            print(f"Headers: {headers}")
            print(f"Data: {data}")
            
            # 使用重试机制调用API
            import requests
            max_retries = 3
            response = None
            
            for attempt in range(max_retries):
                try:
                    response = requests.post(
                        url=api_url,
                        headers=headers,
                        json=data,
                        timeout=30
                    )
                    
                    if response.status_code == 429:  # 频率限制
                        if attempt < max_retries - 1:
                            wait_time = (attempt + 1) * 2  # 指数退避
                            print(f"遇到频率限制，{wait_time}秒后重试...")
                            time.sleep(wait_time)
                            continue
                    break
                except requests.exceptions.RequestException as e:
                    if attempt < max_retries - 1:
                        print(f"请求失败，2秒后重试: {str(e)}")
                        time.sleep(2)
                        continue
                    else:
                        print(f"请求最终失败: {str(e)}")
                        return None
            
            if response is None:
                return None
            
            # 这部分代码只有在使用直接HTTP请求时才会执行
            if 'response' in locals():
                # 打印响应状态和内容
                print(f"Response status: {response.status_code}")
                print(f"Response text: {response.text[:500]}..." if len(response.text) > 500 else f"Response text: {response.text}")
                
                if response.status_code == 200:
                    try:
                        result = response.json()
                        # 根据响应格式提取结果
                        response_format = custom_config.get("response_format", "openai")
                        
                        if response_format == "openai":
                            if "choices" in result and len(result["choices"]) > 0:
                                return result["choices"][0]["message"]["content"].strip()
                        else:
                            # 使用自定义的响应提取路径
                            response_path = custom_config.get("response_path", "")
                            if response_path:
                                return nested_get(result, response_path)
                        
                        # 如果无法提取结果
                        print(f"响应格式不正确: {result}")
                        return f"连接测试成功，但响应格式不正确: {result}"
                    except Exception as e:
                        print(f"解析响应时出错: {str(e)}")
                        return f"连接测试成功，但解析响应时出错: {str(e)}"
                else:
                    error_msg = f"自定义API错误: {response.status_code} - {response.text}"
                    print(error_msg)
                    return error_msg
            
            # 如果没有响应对象，返回错误信息
            return "连接测试失败，请检查配置和日志"
        except Exception as e:
            print(f"调用自定义API时出错: {str(e)}")
            return None