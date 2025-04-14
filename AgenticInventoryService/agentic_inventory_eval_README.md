# Agentic Inventory AI - Evaluation Framework

## Overview
This framework is designed to evaluate **LLM-generated responses** within the **Agentic Inventory AI system**. It provides structured test cases to validate the accuracy and relevance of answers related to **inventory availability, demand forecasting, advanced analysis, what-if generation, and operational decision-making**.

## Purpose
- Validate **AI agent reasoning and response accuracy** for **inventory and demand-related queries of various levels of complexity**.
- Provide a **systematic and repeatable way to test agent outputs** against expected responses.
- Serve as a **benchmarking tool** for refining AI agent performance and preventing regressio or accuracy back-slide over time.

## How It Works

### Structured YAML Format
- Test cases are stored in `config/agentic_inventory_eval.yml` for easy updates and versioning.
- Each test defines:
  - A **user query** (`user_request`)
  - An **expected AI response** (`expected_answer`)
  - Metadata such as difficulty, test case flags, and response format expectations.

### AI Response Validation
- **Exact match** for factual responses (`exact_response: true`)  
- **Flexible validation** for inference-based responses (`exact_response: false`)  
- **Graphical output validation** (e.g., availability charts, demand visualizations)  

### Automated Testing Execution
This will:
- Load test cases from `agentic_inventory_eval.yml `
- Send queries to the **Agentic Inventory AI**
- Compare responses to expected answers
- Generate **pass/fail or graded (0-100) responses**
- Expandable to include expected tools, agents or other workflow components used

## File Structure
/repo-root
│
├── /config
│   ├── agentic_inventory_eval.yml   # YAML file storing LLM Q&A test cases
│
├── /tests
│   ├── test_eval_framework.py  # Python script to validate LLM-generated responses
│
└── eval_README.md
