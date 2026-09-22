from prometheus import (
    AgentRunner,
    AssistantReply,
    Message,
    Model,
    Role,
    RunResult,
    StopReason,
    ToolCall,
    ToolExecutor,
    ToolRegistry,
    ToolSpec,
    Turn,
    Workspace,
    __version__,
    builtin_tools,
    tool,
)


def test_public_exports() -> None:
    assert __version__ == "0.1.0"
    assert AgentRunner
    assert AssistantReply
    assert Message
    assert Model
    assert Role
    assert RunResult
    assert StopReason
    assert ToolCall
    assert ToolExecutor
    assert ToolRegistry
    assert ToolSpec
    assert Turn
    assert Workspace
    assert builtin_tools
    assert tool
