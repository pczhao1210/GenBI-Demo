# GenBI - Generative BI Query System

An intelligent database query and analysis platform based on large language models, supporting natural language to SQL query conversion and intelligent data analysis.

## Features

- 🤖 **Smart Query**: Natural language to SQL query conversion
- 📊 **Data Analysis**: AI-driven data insights  
- 🔗 **Multi-Data Sources**: Support for AWS Athena and MySQL
- 🛠️ **MCP Integration**: Extensible tool ecosystem ([detailed documentation](mcp_servers/mcp_readme_en.md))
- 📋 **API Interface**: Complete RESTful API

## Quick Start

### 1. Environment Setup

```bash
# Activate virtual environment
source .venv/bin/activate  # Linux/Mac
# or
.venv\Scripts\activate     # Windows

# Install dependencies
pip install -r requirements.txt
```

### 2. Start Services

```bash
# Start backend API service
cd backend
uvicorn main:app --reload --port 8000

# Start frontend Streamlit application
streamlit run app.py --server.port 8501
```

### 3. Access Application

- Frontend Interface: http://localhost:8501
- API Documentation: http://localhost:8000/docs
- API Status: http://localhost:8000/health

## User Guide

### Configuration Process

1. **LLM Configuration** - Configure OpenAI, Azure OpenAI, or custom LLM service
2. **Database Configuration** - Connect to AWS Athena or MySQL database
3. **Schema Configuration** - Set up database table structure and field descriptions (required)
4. **Start Querying** - Perform natural language queries and analysis in the chat interface

### Intelligent Intent Recognition

The system uses LLM to automatically identify user intent:
- **Query Intent**: Direct data query execution
- **Analysis Intent**: Generate analysis plan, support multi-turn conversation refinement before execution
- **Rejection Intent**: Automatically reject dangerous insert/update/delete operations

### Supported Query Types

- **Direct Query**: "Show first 10 rows of data"
- **Data Analysis**: "Analyze sales trends and provide recommendations"
  - System will first generate analysis plan
  - Users can supplement or modify the plan
  - Enter "execute" to start analysis
- **Statistical Query**: "Count orders by month"

### Security Features

- **Dual Security Check**: LLM intent recognition + SQL code detection
- **Dangerous Operation Blocking**: Automatically reject INSERT/UPDATE/DELETE operations
- **Rate Limit Handling**: Automatic retry mechanism for API limits

## Project Structure

```
GenBI-Demo/
├── app.py                  # Streamlit main application
├── pages/                  # Page components
├── backend/                # FastAPI backend
├── config/                 # Configuration files
├── utils/                  # Utility modules
├── mcp_servers/            # MCP servers
└── requirements.txt        # Dependencies
```

## MCP Integration

This project supports MCP (Model Context Protocol) server extensions, providing a pluggable tool ecosystem.

- 📖 **[MCP Development Guide](mcp_servers/mcp_readme_en.md)** - Detailed MCP server configuration and development documentation
- 🔧 **Built-in Servers**: MySQL, AWS Athena database connectors
- 🛠️ **Custom Extensions**: Support for creating custom MCP servers
- 🔗 **Standard Protocol**: Based on MCP standard protocol, ensuring compatibility

## Technical Features

### Architecture Design
- **Frontend**: Streamlit provides interactive user interface
- **Backend**: FastAPI provides RESTful API services (optional)
- **Storage**: Local JSON file storage for configuration and Schema
- **LLM Integration**: Support for multiple LLM providers and custom APIs

### Core Functions
- **Intelligent Intent Recognition**: Use LLM to accurately identify user query intent
- **Multi-turn Conversation Analysis**: Analysis tasks support plan generation and iterative optimization
- **Schema Management**: Visual configuration and management of database table structure
- **Security Protection**: Multi-layer security checks to prevent dangerous operations
- **Error Handling**: Comprehensive retry mechanism and error recovery

## License

MIT License