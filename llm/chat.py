import logging
import json
import time  
from typing import List, Optional, Iterator, TypedDict, Annotated, Sequence
from contextlib import contextmanager

from langchain.agents import Tool
from langchain_ollama.chat_models import ChatOllama
from langchain.callbacks.base import BaseCallbackHandler
from langchain_core.messages import (
    AIMessage,
    HumanMessage,
    BaseMessage,
    ToolMessage,
    SystemMessage,
)
from rich.console import Console
from langgraph.graph import StateGraph, END
from langgraph.prebuilt import ToolNode
from langgraph.graph.message import add_messages

from config import Config
from .tools import (
    get_feed_details_tool,
    get_category_feeds_tool,
    fetch_feed_tool,
    search_related_feeds_tool,
    find_feeds_tool,
    crawl_url_tool,
    process_content_tool
)
from database.db import SessionLocal
from langchain_core.prompts import PromptTemplate

logger = logging.getLogger('rss_ai')

PROMPT = """You are a helpful assistant. You have access to a number of tools.
Use them when you need to answer a user's question.
Answer in the language user used.
When the user ask about a specific feed ,You need use the find_feeds tool to find the most relevant feeds for the user's question.
Then you need to use the get_feed_details tool to get the details of the feeds.
When the user ask about a specific topic, you need use the search_related_feeds tool to find the most relevant feeds for the user's question.
"""

class AgentState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]

class StreamingCallbackHandler(BaseCallbackHandler):
    """Callback handler for streaming output to the console."""
    
    def __init__(self, console: Console):
        self.console = console
    
    def on_llm_new_token(self, token: str, **kwargs) -> None:
        """Run on new LLM token. Only available when streaming is enabled."""
        self.console.print(token, end="")

@contextmanager
def get_db_session():
    """Create a new database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

class RSSChat:
    def __init__(self, config: Config, debug: bool = False):
        self.config = config
        self.debug = debug
        self.console = Console()
        self.callback_handler = StreamingCallbackHandler(self.console)
        self.waiting_for_user_input = False
        self.timeout = 120  
        
        # Configure logging based on debug mode
        log_level = logging.DEBUG if debug else logging.INFO
        logger.setLevel(log_level)
        
        # Initialize LLM
        self.llm = ChatOllama(
            base_url=config.ollama.base_url,
            model=config.ollama.chat_model,
            temperature=0,
        )
        logger.debug(
            f"Initialized LLM with model {config.ollama.chat_model} at {config.ollama.base_url}"
        )
        
        # Define tools
        self.tools: List[Tool] = [
            find_feeds_tool,
            get_feed_details_tool,
            get_category_feeds_tool,
            fetch_feed_tool,
            search_related_feeds_tool,
            crawl_url_tool,
            process_content_tool
        ]
        
        self.llm_with_tools = self.llm.bind_tools(self.tools)

        # Define the graph
        workflow = StateGraph(AgentState)

        workflow.add_node("agent", self.run_agent)
        workflow.add_node("action", ToolNode(self.tools))

        workflow.set_entry_point("agent")

        workflow.add_conditional_edges(
            "agent", self.should_continue, {"continue": "action", "end": END}
        )

        workflow.add_edge("action", "agent")

        self.agent_executor = workflow.compile()
    
    def should_continue(self, state: AgentState) -> str:
        if isinstance(state["messages"][-1], AIMessage) and state["messages"][-1].tool_calls:
            return "continue"
        return "end"

    def run_agent(self, state: AgentState, **kwargs):
        """
        Invokes the agent with the current state and returns the new message.
        """
        response = self.llm_with_tools.invoke(state["messages"], **kwargs)
        return {"messages": [response]}

    def chat_stream(self, message: str) -> Iterator[str]:
        """Process a chat message using the agent with streaming output and timeout."""
        try:
            with get_db_session():
                inputs = {"messages": [SystemMessage(content=PROMPT), HumanMessage(content=message)]}
                start_time = time.time()
                for event in self.agent_executor.stream(
                    inputs, config={"callbacks": [self.callback_handler], "recursion_limit": 10}
                ):
                    if time.time() - start_time > self.timeout:
                        yield "\n[red]⚠️ Operation timed out.[/red]"
                        break
                    if "agent" in event:
                        # We will announce the tool call in the "action" step,
                        # so we don't need to yield anything here.
                        pass
                    if "action" in event:
                        action_result: ToolMessage = event["action"]["messages"][-1]
                        yield f"🛠 Tool [[bold green]{action_result.name}[/bold green]] was called.\n\n"
        except Exception as e:
            logger.error(f"Error in chat_stream: {e}")
            yield f"\nError: {e}\n"

    def chat(self, message: str) -> Optional[str]:
        """Process a chat message using the agent (non-streaming)."""
        try:
            with get_db_session():
                inputs = {"messages": [SystemMessage(content=PROMPT), HumanMessage(content=message)]}
                response = self.agent_executor.invoke(inputs, config={"recursion_limit": 10})
                final_message = response["messages"][-1]
                return final_message.content if isinstance(final_message, AIMessage) else str(final_message.content)
        except Exception as e:
            logger.error(f"Error in chat: {e}")
            return f"Error: {e}" 