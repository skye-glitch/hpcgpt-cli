# HPCGPT CLI

HPCCode is a customized CLI tool, based on the [Opencode](https://opencode.ai) CLI providing custom integrations to slurm based HPC enviroments. 

## Available Servers

- slurm-mcp (local)
  - Tools: `accounts`, `sinfo`, `squeue`, `scontrol`
  - Purpose: query accounts, node/partition status, user jobs, and job details.

- illinois-chat-mcp (local)
  - Tools: `delta-docs`, `delta-ai-docs`
  - Purpose: answer questions from Delta and Delta AI documentation (requires `ILLINOIS_CHAT_API_KEY`).

- report-server (local)
  - Tools: `send_support_report`
  - Purpose: email a concise support report with conversation history and system info to the Delta support team.

- atlassian-mcp-server (container)
  - Tools (examples): Jira — `jira_get_issue`, `jira_search_issues`, `jira_create_issue`, `jira_add_comment`, `jira_transition_issue`; Confluence — `confluence_search`, `confluence_get_page`, `confluence_create_page`, `confluence_update_page` (availability depends on config/read-only mode).
  - Purpose: interact with Jira and Confluence for tickets and docs. See Atlassian MCP README: https://github.com/sooperset/mcp-atlassian


## Installation

Right now we are just using a custom configuration file for Opencode so you will need to install opencode itself with:

```bash
curl -fsSL https://opencode.ai/install | bash
```

Once opencode is installed you can set the configuration file and launch opencode.

```bash
export OPENCODE_CONFIG=/path/this/repo/opencode.jsonc
opencode
```

## Environment Configuration

The `example.env` file is a template showing the environment variables that can be set to enable full functionality. You can either export the variables directly or create a `.env` file in the project root.

### Environment Variables

1. **ILLINOIS_CHAT_API_KEY** - API key for Illinois Chat MCP server
   - Get one by creating an account at https://uiuc.chat and selecting the API tab

2. **NCSA_LLM_URL** - URL endpoint for NCSA LLM service
   - Enables using NCSA hosted models 

3. **NCSA_OLLAMA_URL** - URL endpoint for NCSA Ollama service
   - Enables using NCSA hosted models

4. **JIRA_PERSONAL_ACCESS_TOKEN** - Jira token for authticating with the atlassian mcp server
   - Enables quering NCSA jira for information.


Additonally our custom chatbots can be found at:

Delta Chatbot
https://uiuc.chat/Delta-Documentation
Course Name : Delta-Documentation

Delta AI Chatbot 
https://uiuc.chat/DeltaAI-Documentation
Course Name : DeltaAI-Documentation
