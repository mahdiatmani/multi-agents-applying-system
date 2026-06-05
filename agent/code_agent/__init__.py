"""CodeAgent — runtime code generation & self-healing, powered by the CODING_MODEL
(Qwen3-coder).

Public entrypoint: `generate_tool(spec) -> CodeAgentOutcome`.
"""

from agent.code_agent.agent import generate_tool, CodeAgentOutcome  # noqa: F401
