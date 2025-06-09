import logging
import json
import time  
from typing import List, Optional, Iterator
from contextlib import contextmanager

from langchain.agents import Tool, AgentExecutor, create_react_agent
from langchain_ollama import OllamaLLM
from langchain.prompts import PromptTemplate
from langchain.callbacks.base import BaseCallbackHandler
from langchain.schema import AgentAction, AgentFinish, AIMessage, HumanMessage
from rich.console import Console

from config import Config
from .tools import (
    get_feed_details_tool,
    get_category_feeds_tool,
    fetch_feed_tool,
    search_related_feeds_tool,
    crawl_url_tool
)
from database.db import SessionLocal

logger = logging.getLogger('rss_ai')

PROMPT = """You are an AI assistant that helps users explore and understand RSS feeds.

You have access to the following tools:

{tools}

Important Guidelines:
1. Provide clear and concise responses
2. If you can't complete a task in 2-3 steps, ask for user clarification
3. When you have a satisfactory answer, STOP and return it
4. Don't keep trying different tools if you're not making progress
5. If a tool returns an error, ask for user clarification instead of trying other tools blindly
6. If you're not making progress or not sure about the answer, ask for user clarification
7. When you get the content after using the crawl_url tool, summarize the main points in a few sentences,and provide the link to the original content.

Use the following format:
Question: {input}
Thought: (consider if you have enough information and if the task is achievable)
Action: (if needed, one of [{tool_names}])
Action Input: (your input to the tool)
Observation: (tool result)
... (only continue if necessary and you're making progress)
Thought: (decide if you have a satisfactory answer or need user input)
Final Answer: (your response to the user's question)

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
        self.waiting_for_user_input = False
        self.timeout = 30  # 30 seconds timeout
        
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
            get_feed_details_tool,
            get_category_feeds_tool,
            fetch_feed_tool,
            search_related_feeds_tool,
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
        """Format an observation string with better error handling."""
        try:
            observation = json.loads(observation_str)
            if isinstance(observation, dict):
                if observation.get("success") is False:
                    self.waiting_for_user_input = True
                    error_msg = str(observation.get('error', 'Unknown error'))
                    return f"Error: {error_msg}. Please provide more information or try a different approach."
                elif "feed" in observation:
                    feed = observation["feed"]
                    title = str(feed.get('title', 'Untitled'))
                    last_updated = str(feed.get('last_updated', 'Unknown'))
                    description = str(feed.get('description', 'No description'))
                    return f"Feed: {title}\\nLast Updated: {last_updated}\\nDescription: {description}"
                return str(observation)
            return observation_str
        except json.JSONDecodeError:
            self.waiting_for_user_input = True
            return "Error: Unable to parse tool response. Please try again with different parameters."
    
    def chat_stream(self, message: str) -> Iterator[str]:
        """Process a chat message using the agent with streaming output and timeout."""
        try:
            with get_db_session() as db:
                current_input = str(message)
                agent_inputs = {"input": current_input}
                final_answer_sent = False
                start_time = time.time()
                self.waiting_for_user_input = False
                
                for chunk in self.agent_executor.stream(agent_inputs):
                    # Check for timeout
                    if time.time() - start_time > self.timeout:
                        yield "\nOperation timed out. Please try again with a more specific request."
                        break
                        
                    # Check if waiting for user input
                    if self.waiting_for_user_input and not final_answer_sent:
                        yield "\nNeed more information. Please provide additional details or try a different approach."
                        break
                        
                    if isinstance(chunk, (AIMessage, HumanMessage)):
                        if not final_answer_sent:
                            yield str(chunk.content)
                    elif isinstance(chunk, dict):
                        if "intermediate_steps" in chunk:
                            for step in chunk["intermediate_steps"]:
                                action, observation_obj = step
                                if not final_answer_sent:
                                    yield f"\\nThought: {str(action.log)}\\nAction: {str(action.tool)}\\nAction Input: {str(action.tool_input)}\\n"
                                    formatted_observation = self.format_observation(str(observation_obj))
                                    yield f"Observation: {formatted_observation}\\n"
                                    
                                    # Check if we need to stop for user input after each step
                                    if self.waiting_for_user_input:
                                        break
                                        
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
                yield "\nSorry, I encountered an error processing your request. Please try again with a different approach.\n"
        
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