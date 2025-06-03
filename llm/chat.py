import logging
import json
from typing import List, Optional, Iterator
from contextlib import contextmanager

from langchain.agents import Tool, AgentExecutor, create_react_agent
from langchain_ollama import OllamaLLM
from langchain.prompts import PromptTemplate
from langchain.callbacks.base import BaseCallbackHandler
from langchain.schema import AgentAction, AgentFinish, AIMessage, HumanMessage
from rich.console import Console

from config import Config
from .tools import get_feed_details_tool, get_category_feeds_tool, fetch_feed_tool, search_related_feeds_tool, crawl_url_tool
from database.db import SessionLocal

logger = logging.getLogger('rss_ai')

PROMPT = """You are an AI assistant that helps users explore and understand RSS feeds.

You have access to the following tools:

{tools}

Always provide clear and concise responses, focusing on the most relevant information.
If you find feeds or articles, include their titles and links when appropriate.
When a user wants to see the latest content, make sure to fetch/update the feed first.

Important: When using tools, provide the input as a simple string, not a JSON object.
Example: To fetch Hacker News feed, just use the feed name as a string.

Use the following format:

Question: {input}
Thought: you should always think about what to do
Action: the action to take, should be one of [{tool_names}]
Action Input: the input to the action
Observation: the result of the action
... (this Thought/Action/Action Input/Observation can repeat N times)
Thought: I now know the final answer
Final Answer: the final answer to the original input question

Begin!

Question: {input}
{agent_scratchpad}"""

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
        
        # Configure logging based on debug mode
        log_level = logging.DEBUG if debug else logging.INFO
        logger.setLevel(log_level)
        
        # Initialize LLM
        self.llm = OllamaLLM(
            base_url=config.ollama.base_url,
            model=config.ollama.chat_model,
            callbacks=[self.callback_handler]
        )
        logger.debug(f"Initialized LLM with model {config.ollama.chat_model} at {config.ollama.base_url}")
        
        # Define tools
        self.tools: List[Tool] = [
            get_category_feeds_tool,
            get_feed_details_tool,
            search_related_feeds_tool,
            fetch_feed_tool,
            crawl_url_tool
        ]
        
        # Create the agent executor using create_react_agent
        prompt = PromptTemplate.from_template(PROMPT)
        
        self.agent = create_react_agent(
            llm=self.llm,
            tools=self.tools,
            prompt=prompt
        )
        
        self.agent_executor = AgentExecutor.from_agent_and_tools(
            agent=self.agent,
            tools=self.tools,
            handle_parsing_errors=True,
            max_iterations=5,
            verbose=True,
            callbacks=[self.callback_handler]
        )
    
    def format_step(self, step) -> str:
        """Format an agent step for display."""
        action, observation = step
        
        if isinstance(action, AgentAction):
            return f"\nThought: {action.log}\nAction: {action.tool}\nAction Input: {action.tool_input}\nObservation: {observation}\n"
        elif isinstance(action, AgentFinish):
            return f"\nThought: {action.log}\nFinal Answer: {action.return_values.get('output', '')}\n"
        else:
            return f"\nThought: {action}\n"
    
    def format_observation(self, observation_str: str) -> str:
        """Format an observation string (expected to be JSON) for display."""
        try:
            observation = json.loads(observation_str)
            if isinstance(observation, dict):
                # Ensure all string representations are handled correctly
                if observation.get("success") is False:
                    return f"Error: {str(observation.get('error', 'Unknown error'))}"
                elif "feed" in observation:
                    feed = observation["feed"]
                    title = str(feed.get('title', 'Untitled'))
                    last_updated = str(feed.get('last_updated', 'Unknown'))
                    description = str(feed.get('description', 'No description'))
                    return f"Feed: {title}\\nLast Updated: {last_updated}\\nDescription: {description}"
                return str(observation) # Fallback for other dicts
            return observation_str # If not a dict after parsing, return original string
        except json.JSONDecodeError:
            return observation_str # If not valid JSON, return original string
    
    def chat_stream(self, message: str) -> Iterator[str]:
        """Process a chat message using the agent with streaming output."""
        try:
            with get_db_session() as db:
                current_input = str(message)
                agent_inputs = {"input": current_input}
                final_answer_sent = False
                
                for chunk in self.agent_executor.stream(agent_inputs):
                    if isinstance(chunk, (AIMessage, HumanMessage)):
                        if not final_answer_sent:  # Only yield if final answer hasn't been sent
                            yield str(chunk.content)
                    elif isinstance(chunk, dict):
                        if "intermediate_steps" in chunk:
                            for step in chunk["intermediate_steps"]:
                                action, observation_obj = step
                                if not final_answer_sent:  # Only yield if final answer hasn't been sent
                                    yield f"\\nThought: {str(action.log)}\\nAction: {str(action.tool)}\\nAction Input: {str(action.tool_input)}\\n"
                                    yield f"Observation: {self.format_observation(str(observation_obj))}\\n"
                        if "output" in chunk and not final_answer_sent:
                            yield f"Final Answer: {str(chunk['output'])}".strip()
                            final_answer_sent = True
                    elif isinstance(chunk, str) and not final_answer_sent:
                        yield chunk
                
        except Exception as e:
            logger.error(f"Error in chat_stream: {str(e)}")
            if self.debug:
                yield f"\nError: {str(e)}\n"
            else:
                yield "\nSorry, I encountered an error processing your request. Please try again.\n"
        
    def chat(self, message: str) -> Optional[str]:
        """Process a chat message using the agent (non-streaming)."""
        try:
            with get_db_session() as db:
                current_input = str(message)
                agent_inputs = {"input": current_input}
                
                response = self.agent_executor.invoke(agent_inputs)
                
                if isinstance(response, (AIMessage, HumanMessage)):
                    return str(response.content)
                elif isinstance(response, dict):
                    if "intermediate_steps" in response:
                        result = []
                        for step in response["intermediate_steps"]:
                            action, observation_obj = step # observation_obj is now a string
                            result.append(f"\\nThought: {str(action.log)}\\nAction: {str(action.tool)}\\nAction Input: {str(action.tool_input)}")
                            result.append(f"Observation: {self.format_observation(str(observation_obj))}") # Pass string
                        if "output" in response:
                            result.append(f"\\nFinal Answer: {str(response['output'])}".strip())
                        return "\\n".join(result)
                    elif "output" in response:
                        return str(response["output"]).strip()
                elif isinstance(response, str):
                    return response
                
                return None
                
        except Exception as e:
            logger.error(f"Error in chat: {str(e)}")
            if self.debug:
                return f"Error: {str(e)}"
            return "Sorry, I encountered an error processing your request. Please try again." 