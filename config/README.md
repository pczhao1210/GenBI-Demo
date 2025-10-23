# 配置文件说明 - Config Directory

本目录包含GenBI系统的所有配置文件，分为**实际配置**和**模板示例**两类。

## 📁 文件结构

```
config/
├── 📄 README.md                     # 本说明文档
├── 
├── 🔧 实际配置文件 (运行时使用)
│   ├── 🗄️ database_config.json      # 数据库连接配置
│   ├── 🤖 llm_config.json           # LLM服务配置  
│   ├── 🔧 mcp_config.json           # MCP服务器配置
│   └── 📋 schema_config.json        # 数据库表结构配置
├── 
└── 📋 配置模板 (供参考和初始化)
    ├── 📄 example_database_config.json  # 数据库配置模板
    ├── 📄 example_llm_config.json      # LLM配置模板
    └── 📄 example_mcp_config.json      # MCP服务器配置模板
```

## 🔧 实际配置文件

### `database_config.json`
- **用途**: 存储MySQL和AWS Athena数据库连接信息
- **包含**: 主机地址、端口、凭据、SSL设置等
- **管理**: 通过"数据库配置"页面进行可视化配置

### `llm_config.json` 
- **用途**: 存储大语言模型服务配置
- **支持**: OpenAI、Azure OpenAI、自定义API提供商
- **包含**: API密钥、模型名称、参数设置、超时配置
- **管理**: 通过"LLM配置"页面进行设置

### `mcp_config.json`
- **用途**: 存储Model Context Protocol服务器配置
- **功能**: 管理数据库、Web搜索等工具服务器
- **包含**: 服务器命令、参数、状态、能力描述
- **管理**: 通过"MCP管理"页面进行动态配置

### `schema_config.json`
- **用途**: 存储数据库表结构和字段描述信息
- **功能**: 为AI提供准确的数据库上下文
- **包含**: 表名、字段名、数据类型、业务描述
- **管理**: 通过"Schema配置"页面进行可视化编辑

## 📋 配置模板文件

### `example_database_config.json`
- **作用**: 提供数据库配置的标准模板
- **用法**: 复制并修改为实际配置
- **包含**: MySQL和Athena的配置示例

### `example_llm_config.json`
- **作用**: 提供LLM配置的完整模板
- **用法**: 展示所有支持的提供商和参数选项
- **包含**: OpenAI、Azure OpenAI、自定义API的配置示例

### `example_mcp_config.json`
- **作用**: 提供MCP服务器的默认配置模板
- **用法**: 系统初始化时自动使用
- **包含**: 内置MCP服务器的标准配置

## 🔒 安全注意事项

- ✅ **实际配置文件**已在`.gitignore`中排除，不会提交到版本控制
- ✅ **模板文件**可以安全提交，不包含敏感信息
- ⚠️ **不要**在模板文件中放置真实的API密钥或密码
- 🔐 **定期更新**API密钥和数据库密码以确保安全

## 🛠️ 配置管理

### 首次设置
1. 复制对应的example文件为实际配置文件
2. 编辑配置文件填入真实信息
3. 或通过Web界面进行可视化配置

### 备份与恢复
```bash
# 备份配置
cp config/*.json backup/

# 恢复配置  
cp backup/*.json config/
```

### 重置为默认
```bash
# 删除实际配置，系统将使用默认模板
rm config/database_config.json config/llm_config.json
```

---

**GenBI配置系统** - 简单、安全、可视化的配置管理！ ⚙️