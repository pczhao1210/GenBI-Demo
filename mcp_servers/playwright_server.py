#!/usr/bin/env python3
"""
Playwright MCP服务器 - 用于网页搜索和数据抓取
"""

import json
import sys
import asyncio
from playwright.async_api import async_playwright
import logging

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class PlaywrightServer:
    def __init__(self):
        self.playwright = None
        self.browser = None
        
    async def initialize(self):
        """初始化Playwright"""
        try:
            self.playwright = await async_playwright().start()
            self.browser = await self.playwright.chromium.launch(headless=True)
            logger.info("Playwright初始化成功")
        except Exception as e:
            logger.error(f"Playwright初始化失败: {e}")
            raise
    
    async def search_web(self, query: str, max_results: int = 5):
        """网页搜索功能"""
        try:
            if not self.browser:
                await self.initialize()
            
            page = await self.browser.new_page()
            
            # 使用Google搜索
            search_url = f"https://www.google.com/search?q={query}&hl=zh-CN"
            await page.goto(search_url)
            
            # 等待搜索结果加载
            await page.wait_for_selector('div[data-ved]', timeout=10000)
            
            # 提取搜索结果
            results = []
            search_results = await page.query_selector_all('div[data-ved] h3')
            
            for i, result in enumerate(search_results[:max_results]):
                try:
                    title = await result.inner_text()
                    link_element = await result.query_selector('xpath=..')
                    if link_element:
                        href = await link_element.get_attribute('href')
                        results.append({
                            'title': title,
                            'url': href,
                            'snippet': f'搜索结果 {i+1}: {title}'
                        })
                except Exception as e:
                    logger.warning(f"提取搜索结果{i+1}失败: {e}")
            
            await page.close()
            
            return {
                'query': query,
                'results': results,
                'count': len(results)
            }
            
        except Exception as e:
            logger.error(f"网页搜索失败: {e}")
            return {
                'error': f'搜索失败: {str(e)}',
                'query': query,
                'results': []
            }
    
    async def fetch_page_content(self, url: str):
        """获取网页内容"""
        try:
            if not self.browser:
                await self.initialize()
                
            page = await self.browser.new_page()
            await page.goto(url, wait_until='networkidle')
            
            # 提取页面文本内容
            content = await page.evaluate('''
                () => {
                    // 移除脚本和样式标签
                    const scripts = document.querySelectorAll('script, style');
                    scripts.forEach(el => el.remove());
                    
                    // 获取主要内容区域
                    const mainContent = document.querySelector('main, article, .content, #content') || document.body;
                    return mainContent.innerText.trim();
                }
            ''')
            
            title = await page.title()
            await page.close()
            
            return {
                'url': url,
                'title': title,
                'content': content[:2000],  # 限制内容长度
                'length': len(content)
            }
            
        except Exception as e:
            logger.error(f"获取页面内容失败: {e}")
            return {
                'error': f'页面获取失败: {str(e)}',
                'url': url
            }
    
    async def close(self):
        """关闭浏览器"""
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()

# 全局服务器实例
playwright_server = PlaywrightServer()

async def handle_request(method: str, params: dict):
    """处理MCP请求"""
    try:
        if method == "get_server_info":
            # 返回服务器信息
            return {
                "result": {
                    "name": "playwright",
                    "description": "网页数据抓取服务",
                    "capabilities": ["web_scraping", "external_data", "automation", "search_engine"],
                    "type": "stdio",
                    "version": "1.0.0",
                    "methods": ["search_web", "fetch_page"],
                    "status": "ready"
                }
            }
        
        elif method == "search_web":
            query = params.get("query", "")
            max_results = params.get("max_results", 5)
            
            if not query:
                return {"error": "搜索查询不能为空"}
            
            result = await playwright_server.search_web(query, max_results)
            return {"result": result}
            
        elif method == "fetch_page":
            url = params.get("url", "")
            
            if not url:
                return {"error": "URL不能为空"}
            
            result = await playwright_server.fetch_page_content(url)
            return {"result": result}
            
        else:
            return {"error": f"不支持的方法: {method}"}
            
    except Exception as e:
        logger.error(f"请求处理失败: {e}")
        return {"error": f"请求处理失败: {str(e)}"}

def main():
    """主函数 - 处理标准输入输出"""
    async def process_single_request():
        """处理单个请求"""
        try:
            # 从标准输入读取请求
            for line in sys.stdin:
                request = json.loads(line.strip())
                method = request.get("method", "")
                params = request.get("params", {})
                
                # 处理请求
                response = await handle_request(method, params)
                
                # 输出响应
                print(json.dumps(response, ensure_ascii=False))
                sys.stdout.flush()
                break  # 处理完一个请求就退出
                
        except json.JSONDecodeError:
            print(json.dumps({"error": "无效的JSON请求"}, ensure_ascii=False))
            sys.stdout.flush()
        except Exception as e:
            print(json.dumps({"error": f"处理请求时发生错误: {str(e)}"}, ensure_ascii=False))
            sys.stdout.flush()
    
    # 运行异步处理
    try:
        asyncio.run(process_single_request())
    except Exception as e:
        print(json.dumps({"error": f"启动失败: {str(e)}"}, ensure_ascii=False))
    finally:
        # 清理资源
        try:
            asyncio.run(playwright_server.close())
        except:
            pass

if __name__ == "__main__":
    main()