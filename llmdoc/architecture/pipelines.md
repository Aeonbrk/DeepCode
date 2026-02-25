# Pipelines

This document describes the main workflow entrypoints and the phases they run.

## Main Entrypoints

- Paper/file/URL pipeline:
  `workflows/agent_orchestration_engine.py:execute_multi_agent_research_pipeline`
- Chat pipeline:
  `workflows/agent_orchestration_engine.py:execute_chat_based_planning_pipeline`
- Requirement analysis:
  `workflows/agent_orchestration_engine.py:execute_requirement_analysis_workflow`

## Paper/File/URL Pipeline (Multi-Agent Research)

`execute_multi_agent_research_pipeline(...)` is a phase orchestrator.
It coordinates specialized agents and tool servers.

Typical phase order (see `workflows/agent_orchestration_engine.py`):

1. Research analysis + input acquisition
   - `orchestrate_research_analysis_agent(...)`
   - `run_research_analyzer(...)`
   - `run_resource_processor(...)`
2. Workspace setup
   - `synthesize_workspace_infrastructure_agent(...)`
   - Uses `utils/file_processor.py:FileProcessor`
3. Document preprocessing (optional)
   - `orchestrate_document_preprocessing_agent(...)`
   - Uses `workflows/agents/document_segmentation_agent.py` when segmentation is
     enabled and the input is large
4. Code planning
   - `orchestrate_code_planning_agent(...)`
   - Uses `run_code_analyzer(...)` (fan-out analysis + planner via `ParallelLLM`)
5. Reference + repository acquisition (conditional)
   - `orchestrate_reference_intelligence_agent(...)`
   - `automate_repository_acquisition_agent(...)`
6. Codebase intelligence / indexing (conditional)
   - `orchestrate_codebase_intelligence_agent(...)`
   - `workflows/codebase_index_workflow.py:run_codebase_indexing`
7. Implementation
   - `synthesize_code_implementation_agent(...)`
   - Delegates to:
     - `workflows/code_implementation_workflow.py:CodeImplementationWorkflow`, or
     - `workflows/code_implementation_workflow_index.py:CodeImplementationWorkflowWithIndex`

The major runtime switch is `enable_indexing`, which influences whether indexing
workflows are run and which implementation workflow class is used.

## Chat Pipeline

`execute_chat_based_planning_pipeline(...)` bypasses paper-specific phases and
runs a planning + implementation flow starting from a natural-language
requirement.

The CLI routes `input_type == "chat"` to this pipeline via:

- `cli/workflows/cli_workflow_adapter.py:execute_chat_pipeline`

## Requirement Analysis

`execute_requirement_analysis_workflow(...)` supports requirement-analysis
subtasks (question generation and requirement summarization) using
`workflows/agents/requirement_analysis_agent.py:RequirementAnalysisAgent`.

Both the CLI and UIs expose this as a separate workflow:

- CLI:
  `cli/workflows/cli_workflow_adapter.py:execute_requirement_analysis_workflow`
- Classic UI:
  `ui/handlers.py:handle_requirement_analysis_workflow`
- New UI:
  `new_ui/backend/services/requirement_service.py`
