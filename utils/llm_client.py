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
    
    def _get_timeout_by_request_type(self, prompt: str) -> int:
        """根据意图分类确定超时时间"""
        # 从全局LLM配置中获取超时设置
        timeout_config = self.config.get("timeout", {})
        
        if isinstance(timeout_config, int):
            # 如果timeout是单个数字，直接返回
            return timeout_config
        elif isinstance(timeout_config, dict):
            # 如果timeout是字典，根据意图分类返回
            intent_type = self._classify_intent_type(prompt)
            return timeout_config.get(intent_type, timeout_config.get("default", 70))
        else:
            # 默认按意图分类设置超时时间
            intent_type = self._classify_intent_type(prompt)
            # 默认超时时间映射
            default_timeout_map = {
                "query": 70,       # 查询意图：70秒
                "analysis": 240,   # 分析意图：240秒
            }
            return default_timeout_map.get(intent_type, 70)
    
    def _classify_intent_type(self, prompt: str) -> str:
        """根据提示内容分类意图类型"""
        # 如果提示中包含意图类型标记，直接提取
        if "[INTENT_TYPE:" in prompt:
            start = prompt.find("[INTENT_TYPE:") + 13
            end = prompt.find("]", start)
            if end != -1:
                return prompt[start:end].strip()
        
        prompt_lower = prompt.lower()
        
        # 分析意图关键词
        analysis_keywords = [
            "分析", "analysis", "意图识别", "identify_intent", "生成分析计划", 
            "generate_analysis_plan", "执行分析计划", "execute_analysis_plan",
            "复杂", "complex", "深度分析", "统计分析", "数据挖掘", "机器学习"
        ]
        
        # 检查分析意图关键词
        if any(keyword in prompt_lower for keyword in analysis_keywords):
            return "analysis"
            
        # 默认为查询意图
        return "query"
    
    def generate_sql(self, prompt: str, request_type: Optional[str] = None, tools: List[Dict] = None) -> Optional[str]:
        """根据提示生成SQL查询"""
        if self.provider == "openai":
            return self._call_openai(prompt, request_type)
        elif self.provider == "azure_openai":
            return self._call_azure_openai(prompt, request_type)
        elif self.provider == "custom":
            return self._call_custom(prompt, request_type)
        elif self.provider == "openai_sdk":
            return self._call_openai_sdk(prompt, request_type, tools)
        return None
    
    def generate_response(self, prompt: str, request_type: Optional[str] = None, tools: List[Dict] = None) -> Optional[str]:
        """生成LLM响应，支持工具调用"""
        return self.generate_sql(prompt, request_type, tools)
    
    def generate_response_with_tools(self, messages: List[Dict], tools: List[Dict] = None) -> Dict[str, Any]:
        """生成支持工具调用的响应"""
        if self.provider == "openai_sdk":
            return self._call_openai_sdk_with_tools(messages, tools)
        else:
            # 其他provider暂不支持工具调用，回退到普通模式
            last_message = messages[-1] if messages else {"content": ""}
            response = self.generate_response(last_message.get("content", ""))
            return {
                "content": response,
                "tool_calls": None
            }
        
    def _call_openai_sdk(self, prompt: str, request_type: Optional[str] = None) -> Optional[str]:
        """使用OpenAI SDK调用API"""
        try:
            openai_config = self.config.get("openai", {})
            params = self.config.get("parameters", {})
            
            # 获取动态超时时间
            if request_type:
                # 临时设置意图类型用于超时计算
                temp_prompt = f"[INTENT_TYPE:{request_type}] {prompt}"
                timeout_seconds = self._get_timeout_by_request_type(temp_prompt)
            else:
                timeout_seconds = self._get_timeout_by_request_type(prompt)
            
            # 设置OpenAI SDK的配置
            openai.api_key = openai_config.get("api_key")
            if openai_config.get("organization"):
                openai.organization = openai_config.get("organization")
            if openai_config.get("base_url"):
                openai.base_url = openai_config.get("base_url")
                
            # 调用API
            api_params = {
                "model": openai_config.get("model", "gpt-3.5-turbo"),
                "messages": [{"role": "user", "content": prompt}]
            }
            
            # 处理模型参数兼容性
            model_name = openai_config.get("model", "gpt-3.5-turbo").lower()
            
            # 检测是否为新一代模型（o1系列、gpt-5系列等）
            is_new_generation_model = any(x in model_name for x in ["o1-", "gpt-5", "gpt-5-mini"])
            # 检测是否为较新的模型（gpt-4o等）
            is_newer_model = any(x in model_name for x in ["gpt-4o", "gpt-4-turbo"])
            
            # 对于新一代模型，只使用基本参数
            if is_new_generation_model:
                # o1系列和gpt-5系列等模型只支持默认参数，不添加temperature等
                pass
            else:
                # 其他模型可以使用temperature参数
                if params.get("temperature") is not None:
                    api_params["temperature"] = params.get("temperature", 0.7)
            
            # 处理max_tokens参数兼容性
            if params.get("max_tokens") is not None:
                if is_newer_model or is_new_generation_model:
                    # 新模型使用max_completion_tokens
                    api_params["max_completion_tokens"] = params.get("max_tokens", 4000)
                else:
                    # 旧模型使用max_tokens
                    api_params["max_tokens"] = params.get("max_tokens", 4000)
            
            if params.get("top_p") is not None and not is_new_generation_model:
                # 新一代模型可能也不支持top_p参数
                api_params["top_p"] = params.get("top_p", 0.9)
            
            response = openai.chat.completions.create(**api_params)
            
            return response.choices[0].message.content.strip()
        except Exception as e:
            print(f"使用OpenAI SDK调用API时出错: {str(e)}")
            return None
    
    def _call_openai(self, prompt: str, request_type: Optional[str] = None) -> Optional[str]:
        """调用OpenAI API"""
        try:
            openai_config = self.config.get("openai", {})
            params = self.config.get("parameters", {})
            
            # 获取动态超时时间
            if request_type:
                # 临时设置意图类型用于超时计算
                temp_prompt = f"[INTENT_TYPE:{request_type}] {prompt}"
                timeout_seconds = self._get_timeout_by_request_type(temp_prompt)
            else:
                timeout_seconds = self._get_timeout_by_request_type(prompt)
            
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {openai_config.get('api_key')}"
            }
            
            if openai_config.get("organization"):
                headers["OpenAI-Organization"] = openai_config.get("organization")
            
            data = {
                "model": openai_config.get("model", "gpt-3.5-turbo"),
                "messages": [{"role": "user", "content": prompt}]
            }
            
            # 处理模型参数兼容性
            model_name = openai_config.get("model", "gpt-3.5-turbo").lower()
            
            # 检测是否为新一代模型（o1系列、gpt-5系列等）
            is_new_generation_model = any(x in model_name for x in ["o1-", "gpt-5", "gpt-5-mini"])
            # 检测是否为较新的模型（gpt-4o等）
            is_newer_model = any(x in model_name for x in ["gpt-4o", "gpt-4-turbo"])
            
            # 对于新一代模型，只使用基本参数
            if is_new_generation_model:
                # o1系列等模型只支持默认参数，不添加temperature等
                pass
            else:
                # 其他模型可以使用temperature参数
                if params.get("temperature") is not None:
                    data["temperature"] = params.get("temperature", 0.7)
            
            # 处理max_tokens参数兼容性
            if params.get("max_tokens") is not None:
                if is_newer_model or is_new_generation_model:
                    # 新模型使用max_completion_tokens
                    data["max_completion_tokens"] = params.get("max_tokens", 4000)
                else:
                    # 旧模型使用max_tokens
                    data["max_tokens"] = params.get("max_tokens", 4000)
            
            if params.get("top_p") is not None:
                data["top_p"] = params.get("top_p", 0.9)
            
            response = requests.post(
                f"{openai_config.get('base_url', 'https://api.openai.com/v1')}/chat/completions",
                headers=headers,
                json=data,
                timeout=timeout_seconds
            )
            
            # 检查响应状态码
            if response.status_code == 200:
                # 检查响应内容是否为空
                if not response.text.strip():
                    print(f"OpenAI API返回空响应")
                    return None
                
                try:
                    result = response.json()
                    if "choices" in result and len(result["choices"]) > 0:
                        content = result["choices"][0]["message"]["content"]
                        return content.strip() if content else None
                    else:
                        print(f"OpenAI API响应格式错误: 缺少choices字段")
                        return None
                except json.JSONDecodeError as json_error:
                    print(f"OpenAI API响应JSON解析失败: {json_error}")
                    print(f"原始响应内容: {response.text[:500]}...")  # 只显示前500字符
                    return None
            else:
                print(f"OpenAI API错误: {response.status_code}")
                try:
                    error_detail = response.json()
                    print(f"错误详情: {error_detail}")
                except:
                    print(f"错误响应(非JSON): {response.text}")
                return None
        except requests.exceptions.Timeout:
            print(f"调用OpenAI API超时")
            return None
        except requests.exceptions.ConnectionError:
            print(f"连接OpenAI API失败")
            return None
        except Exception as e:
            print(f"调用OpenAI API时出错: {str(e)}")
            return None
    
    def _call_azure_openai(self, prompt: str, request_type: Optional[str] = None) -> Optional[str]:
        """调用Azure OpenAI API"""
        try:
            azure_config = self.config.get("azure_openai", {})
            params = self.config.get("parameters", {})
            
            # 获取动态超时时间
            if request_type:
                # 临时设置意图类型用于超时计算
                temp_prompt = f"[INTENT_TYPE:{request_type}] {prompt}"
                timeout_seconds = self._get_timeout_by_request_type(temp_prompt)
            else:
                timeout_seconds = self._get_timeout_by_request_type(prompt)
            
            headers = {
                "Content-Type": "application/json",
                "api-key": azure_config.get("api_key")
            }
            
            data = {
                "messages": [{"role": "user", "content": prompt}]
            }
            
            # 处理模型参数兼容性
            model_name = azure_config.get("deployment_name", "").lower()
            
            # 检测是否为新一代模型（o1系列、gpt-5系列等）
            is_new_generation_model = any(x in model_name for x in ["o1-", "gpt-5", "gpt-5-mini"])
            # 检测是否为较新的模型（gpt-4o等）
            is_newer_model = any(x in model_name for x in ["gpt-4o", "gpt-4-turbo"])
            
            # 对于新一代模型，只使用基本参数
            if is_new_generation_model:
                # o1系列和gpt-5系列等模型只支持默认参数，不添加temperature等
                pass
            else:
                # 其他模型可以使用temperature参数
                if params.get("temperature") is not None:
                    data["temperature"] = params.get("temperature", 0.7)
            
            # 处理max_tokens参数兼容性
            if params.get("max_tokens") is not None:
                if is_newer_model or is_new_generation_model:
                    # 新模型使用max_completion_tokens
                    data["max_completion_tokens"] = params.get("max_tokens", 4000)
                else:
                    # 旧模型使用max_tokens
                    data["max_tokens"] = params.get("max_tokens", 4000)
                    
            if params.get("top_p") is not None and not is_new_generation_model:
                # 新一代模型可能也不支持top_p参数
                data["top_p"] = params.get("top_p", 0.9)
            
            endpoint = azure_config.get("endpoint", "").rstrip("/")
            deployment = azure_config.get("deployment_name")
            
            # 使用v1 endpoint格式，不需要api_version参数
            if "/openai/v1" in endpoint:
                # 新的v1 endpoint格式
                url = f"{endpoint}/chat/completions"
                # 在请求体中添加model参数
                data["model"] = deployment
            else:
                # 传统的deployment格式，保留api_version以兼容旧配置
                api_version = azure_config.get("api_version", "2024-02-01")
                url = f"{endpoint}/openai/deployments/{deployment}/chat/completions?api-version={api_version}"
            
            response = requests.post(url, headers=headers, json=data, timeout=timeout_seconds)
            
            # 检查响应状态码
            if response.status_code == 200:
                # 检查响应内容是否为空
                if not response.text.strip():
                    print(f"Azure OpenAI API返回空响应")
                    return None
                
                try:
                    result = response.json()
                    if "choices" in result and len(result["choices"]) > 0:
                        content = result["choices"][0]["message"]["content"]
                        return content.strip() if content else None
                    else:
                        print(f"Azure OpenAI API响应格式错误: 缺少choices字段")
                        return None
                except json.JSONDecodeError as json_error:
                    print(f"Azure OpenAI API响应JSON解析失败: {json_error}")
                    print(f"原始响应内容: {response.text[:500]}...")
                    return None
            else:
                print(f"Azure OpenAI API错误: {response.status_code}")
                try:
                    error_detail = response.json()
                    print(f"错误详情: {error_detail}")
                except:
                    print(f"错误响应(非JSON): {response.text}")
                return None
        except requests.exceptions.Timeout:
            print(f"调用Azure OpenAI API超时")
            return None
        except requests.exceptions.ConnectionError:
            print(f"连接Azure OpenAI API失败")
            return None
        except Exception as e:
            print(f"调用Azure OpenAI API时出错: {str(e)}")
            return None
    
    def _call_custom(self, prompt: str, request_type: Optional[str] = None) -> Optional[str]:
        """调用自定义LLM API"""
        try:
            custom_config = self.config.get("custom", {})
            params = self.config.get("parameters", {})
            
            # 获取动态超时时间
            if request_type:
                # 临时设置意图类型用于超时计算
                temp_prompt = f"[INTENT_TYPE:{request_type}] {prompt}"
                timeout_seconds = self._get_timeout_by_request_type(temp_prompt)
            else:
                timeout_seconds = self._get_timeout_by_request_type(prompt)
            
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
                    "messages": [{"role": "user", "content": prompt}]
                }
                
                # 添加可选参数
                if params.get("temperature") is not None:
                    data["temperature"] = params.get("temperature", 0.7)
                if params.get("max_tokens") is not None:
                    data["max_tokens"] = params.get("max_tokens", 4000)
                if params.get("top_p") is not None:
                    data["top_p"] = params.get("top_p", 0.9)
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
                        timeout=timeout_seconds
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
                    except json.JSONDecodeError:
                        return f"连接测试成功，但响应不是有效的JSON: {response.text}"
                else:
                    return f"自定义API错误: {response.status_code} - {response.text}"
            except Exception as e:
                return f"自定义API调用异常: {str(e)}"
    
    def _call_openai_sdk_with_tools(self, messages: List[Dict], tools: List[Dict] = None) -> Dict[str, Any]:
        """使用OpenAI SDK调用API，支持工具调用"""
        try:
            openai_config = self.config.get("openai", {})
            params = self.config.get("parameters", {})
            
            # 设置OpenAI SDK的配置
            openai.api_key = openai_config.get("api_key")
            if openai_config.get("organization"):
                openai.organization = openai_config.get("organization")
            if openai_config.get("base_url"):
                openai.base_url = openai_config.get("base_url")
            
            # 构建API参数
            api_params = {
                "model": openai_config.get("model", "gpt-4-turbo"),
                "messages": messages
            }
            
            # 添加工具定义
            if tools and len(tools) > 0:
                api_params["tools"] = tools
                api_params["tool_choice"] = "auto"
            
            # 处理模型参数
            model_name = openai_config.get("model", "gpt-4-turbo").lower()
            is_new_generation_model = any(x in model_name for x in ["o1-", "gpt-5"])
            
            if not is_new_generation_model:
                if params.get("temperature") is not None:
                    api_params["temperature"] = params.get("temperature", 0.7)
                if params.get("max_tokens") is not None:
                    api_params["max_completion_tokens"] = params.get("max_tokens", 4000)
            
            # 调用API
            response = openai.chat.completions.create(**api_params)
            
            # 处理响应
            message = response.choices[0].message
            
            result = {
                "content": message.content,
                "tool_calls": None
            }
            
            # 检查是否有工具调用
            if hasattr(message, 'tool_calls') and message.tool_calls:
                result["tool_calls"] = []
                for tool_call in message.tool_calls:
                    result["tool_calls"].append({
                        "id": tool_call.id,
                        "type": tool_call.type,
                        "function": {
                            "name": tool_call.function.name,
                            "arguments": tool_call.function.arguments
                        }
                    })
            
            return result
            
        except Exception as e:
            print(f"OpenAI SDK工具调用失败: {e}")
            return {
                "content": f"API调用失败: {str(e)}",
                "tool_calls": None
            }
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