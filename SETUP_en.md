# GenBI Installation and Configuration Guide

## System Requirements

- Python 3.8+
- pip

## Installation Steps

### 1. Clone Project

```bash
git clone https://github.com/pczhao1210/GenBI-Demo.git
cd GenBI-Demo
```

### 2. Create Virtual Environment

```bash
python -m venv .venv
source .venv/bin/activate  # Linux/Mac
# or
.venv\Scripts\activate     # Windows
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

### 4. Configuration File Setup

#### LLM Configuration
Copy example configuration file and modify:
```bash
cp config/example_llm_config.json config/llm_config.json
```

Edit `config/llm_config.json` and fill in your API keys and configuration.

#### Database Configuration
```bash
cp config/example_database_config.json config/database_config.json
```

Edit `config/database_config.json` and fill in your database connection information.

### 5. Start Application

#### Quick Start (Recommended)
```bash
./start.sh
```

#### Manual Start

##### Start Backend API (Optional)
```bash
cd backend
uvicorn main:app --reload --port 8000
```

##### Start Frontend Application
```bash
streamlit run app.py --server.port 8501
```

### 6. Access Application

- Frontend Interface: http://localhost:8501
- API Documentation: http://localhost:8000/docs (if backend is started)

## Configuration Details

### LLM Provider Support
- OpenAI
- Azure OpenAI
- Custom API (OpenAI-compatible format)

### Database Support
- MySQL
- AWS Athena

## Usage Workflow

1. Configure LLM service
2. Configure database connection
3. Set up database Schema
4. Start intelligent querying and analysis

## Important Notes

- Please keep API keys secure and do not commit to version control
- First-time users need to set up table structure in Schema configuration page
- Recommend enabling "Avoid executing dangerous code" option to ensure data security