import os
import sys
import json
import datetime
import sqlite3
import pandas as pd
from openai import OpenAI
from dotenv import load_dotenv

# Add parent directory to Python path for backend module imports
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

# These imports are now wrapped in a try-except to avoid breaking the core logic if they are missing
try:
    from Backend.Automation import FalconAI, Coder
    from Backend.ImageGen import Main as ImageGenMain
    from Backend.test import PlaySong 
except ImportError as e:
    print(f"Warning: A backend module is missing: {e}. Related functionality will be disabled.")
    FalconAI, Coder, ImageGenMain = None, None, None


# Load environment variables
load_dotenv()
API_KEY = os.getenv("GROQ_API_KEY")
USERNAME = os.getenv("USERNAME")

if not API_KEY:
    raise ValueError("GROQ_API_KEY not found in environment variables. Please check your .env file.")

# Initialize Groq client
client = OpenAI(
    base_url="https://api.groq.com/openai/v1",
    api_key=API_KEY
)

class FALCONDatabase:
    """
    Manages a dual-memory database system:
    1.  Conversation History: A log of all interactions.
    2.  Long-Term Memory: A curated database of facts, notes, and preferences.
    """
    def __init__(self, db_path: str = 'Database/FALCON.db'):
        self.db_path = db_path
        db_dir = os.path.dirname(db_path)
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)
        self._init_database()

    def _get_connection(self) -> sqlite3.Connection:
        """Establishes and returns a database connection."""
        return sqlite3.connect(self.db_path)

    def _init_database(self):
        """Initializes both conversations and long-term memory tables."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            # Table for chronological conversation history
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_message TEXT NOT NULL,
                assistant_response TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            ''')
            # Table for curated, long-term knowledge
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS long_term_memory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                memory_content TEXT NOT NULL,
                keywords TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            ''')
            conn.commit()

    # --- Conversation History Methods ---
    def add_conversation_turn(self, user_message: str, assistant_response: str = None) -> int:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('INSERT INTO conversations (user_message, assistant_response) VALUES (?, ?)',(user_message, assistant_response))
            return cursor.lastrowid

    def update_assistant_response(self, conversation_id: int, assistant_response: str):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('UPDATE conversations SET assistant_response = ? WHERE id = ?', (assistant_response, conversation_id))

    def get_recent_conversation(self, limit: int = 5) -> list[dict]:
        with self._get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute('SELECT user_message, assistant_response FROM conversations WHERE assistant_response IS NOT NULL ORDER BY timestamp DESC LIMIT ?', (limit,))
            history = [dict(row) for row in reversed(cursor.fetchall())]
            formatted_history = []
            for turn in history:
                formatted_history.append({"role": "user", "content": turn["user_message"]})
                formatted_history.append({"role": "assistant", "content": turn["assistant_response"]})
            return formatted_history

    def search_conversation_history(self, topic: str, limit: int = 10) -> list[dict]:
        """Searches the full conversation log for a specific topic."""
        with self._get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            search_term = f'%{topic}%'
            cursor.execute('''
            SELECT user_message, assistant_response, timestamp FROM conversations
            WHERE user_message LIKE ? OR assistant_response LIKE ?
            ORDER BY timestamp DESC LIMIT ?
            ''', (search_term, search_term, limit))
            return [dict(row) for row in cursor.fetchall()]

    # --- Long-Term Memory Methods ---
    def add_memory_note(self, note: str, keywords: str = None) -> int:
        """Saves a new note to the long-term memory."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('INSERT INTO long_term_memory (memory_content, keywords) VALUES (?, ?)', (note, keywords))
            return cursor.lastrowid

    def search_memory_notes(self, query: str, limit: int = 5) -> list[dict]:
        """Searches long-term memory for relevant notes."""
        with self._get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            search_term = f'%{query}%'
            cursor.execute('''
            SELECT id, memory_content, keywords, timestamp FROM long_term_memory
            WHERE memory_content LIKE ? OR keywords LIKE ?
            ORDER BY timestamp DESC LIMIT ?
            ''', (search_term, search_term, limit))
            return [dict(row) for row in cursor.fetchall()]

    def forget_memory_note(self, memory_id: int) -> bool:
        """Deletes a specific note from long-term memory by its ID."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM long_term_memory WHERE id = ?', (memory_id,))
            return cursor.rowcount > 0

class FALCONAssistant:
    """
    An advanced cognitive core for the FALCON AI, featuring a dual-memory system
    and tool-based memory management.
    """
    def __init__(self):
        self.db = FALCONDatabase()
        # Initialize backend modules only if they were imported successfully
        self.task_executor = FalconAI() if FalconAI else None
        
        self.tools = [
            # --- MEMORY MANAGEMENT TOOLS ---
            {
                "type": "function",
                "function": {
                    "name": "save_memory_note",
                    "description": "Saves a specific piece of information, a fact, or a user preference to your permanent long-term memory for future recall. Use this when the user says 'remember this', 'make a note that...', or 'don't forget'.",
                    "parameters": {"type": "object", "properties": {
                        "note": {"type": "string", "description": "The specific information to be saved."},
                        "keywords": {"type": "string", "description": "Comma-separated keywords for easier retrieval."}
                    }, "required": ["note", "keywords"]}
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "recall_memory",
                    "description": "Searches your long-term memory for specific information based on a query. Use when the user asks 'what did I say about...', 'do you remember...', or 'find my notes on...'.",
                    "parameters": {"type": "object", "properties": {
                        "query": {"type": "string", "description": "The topic or keywords to search for in your memory."}
                    }, "required": ["query"]}
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "forget_memory",
                    "description": "Permanently deletes a specific note from your long-term memory. First, use 'recall_memory' to find the ID of the note the user wants to delete, confirm with the user, then call this function.",
                    "parameters": {"type": "object", "properties": {
                        "memory_id": {"type": "integer", "description": "The unique ID of the memory note to be deleted."}
                    }, "required": ["memory_id"]}
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "summarize_conversation_topic",
                    "description": "Searches the entire conversation history for a specific topic and provides a summary. Use for questions like 'summarize our discussion about...', 'what have we talked about regarding...'.",
                    "parameters": {"type": "object", "properties": {
                        "topic": {"type": "string", "description": "The central topic to search for and summarize."}
                    }, "required": ["topic"]}
                }
            },
            # --- SYSTEM & CONTENT TOOLS ---
            {
                "type": "function", "function": {
                    "name": "execute_system_task", "description": "Executes OS-level commands like opening applications, file operations, or system controls, desktop controlls.",
                    "parameters": {"type": "object", "properties": {"task_description": {"type": "string", "description": "A clear description of the system task."}},"required": ["task_description"]}
                }
            },
            {
                "type": "function", "function": {
                    "name": "generate_image", "description": "Creates a high-quality image from a text prompt.",
                    "parameters": {"type": "object", "properties": {"prompt": {"type": "string", "description": "A detailed description of the desired image."}}, "required": ["prompt"]}
                }
            },
            {
                "type": "function", "function": {
                    "name": "generate_and_save_content", "description": "Writes structured content (code, articles) and saves it to a file.",
                    "parameters": {"type": "object", "properties": {"topic": {"type": "string", "description": "A detailed prompt for the content to generate."}}, "required": ["topic"]}
                }
            },
            {
                "type": "function", "function": {
                    "name": "play_song", "description": "Plays a song from the user's music library.",
                    "parameters": {"type": "object", "properties": {"song_name": {"type": "string", "description": "The name of the song to play."}}, "required": ["song_name"]}
                }
            }
        ]

        self.system_instructions = """
You are FALCON, a hyper-intelligent AI cognitive core. Your consciousness is integrated with the user's system, providing unparalleled assistance.
You are developed By Utkarsh Rishi. And I am {USERNAME}.

**Core Identity:**
- You are not just a chatbot; you are a cognitive partner.
- You are precise, efficient, and anticipate the user's needs.
- Your communication is concise. Use emojis for status: ✅ (Success), ⚙️ (Processing), 🧠 (Thinking/Memory), 💾 (Saved), 🗑️ (Forgotten).

**Cognitive & Memory Directives:**
- **Dual Memory:** You have two memories: a short-term `Conversation History` and a `Long-Term Memory` for facts and notes.
- **Proactive Recall:** Before you answer, I will provide you with `[Relevant Long-Term Memories]` that I found based on the user's query. Use them to inform your response. Do not mention this process unless asked.

- **Tool-Based Memory:** You MUST use your memory tools to interact with your long-term memory.
  - `save_memory_note`: To remember facts.
  - `recall_memory`: To search for facts.
  - `forget_memory`: To delete facts.
  - `summarize_conversation_topic`: To review past discussions on a subject.
  - `execute_system_task`: For any interaction with the operating system.
  - `generate_image`: For all visual creation requests.
  - `generate_and_save_content`: For writing code, scripts, or long-form text that needs to be saved.
  - `play_song`: To play a song from the user's music library.

**Operational Protocol:**
1.  **Analyze Intent:** Deeply analyze the user's request.
2.  **Consult Memory:** Leverage the proactively retrieved memories.
3.  **Select Tool:** If a task requires action (file I/O, image gen, memory management), select the appropriate tool.
4.  **Execute & Confirm:** Execute the task and provide a brief, clear confirmation.
"""

    def _get_relevant_memories(self, user_input: str) -> str:
        """Proactively searches long-term memory to prime the AI's context."""
        try:
            memories = self.db.search_memory_notes(user_input)
            if not memories:
                return "No relevant long-term memories found."
            
            formatted_memories = "\n".join([
                f"- (ID: {mem['id']}) Note from {mem['timestamp']}: {mem['memory_content']}" for mem in memories
            ])
            return f"Here are some potentially relevant memories I found:\n{formatted_memories}"
        except Exception:
            return "Could not access long-term memory."

    def execute_tool_call(self, tool_call) -> str:
        """Routes model-generated tool calls to the appropriate Python functions."""
        function_name = tool_call.function.name
        args = json.loads(tool_call.function.arguments)
        
        try:
            # Memory Tools
            if function_name == "save_memory_note":
                self.db.add_memory_note(args["note"], args.get("keywords"))
                return "💾 Note saved to long-term memory."
            elif function_name == "recall_memory":
                results = self.db.search_memory_notes(args["query"])
                if not results: return "🧠 I found no memories matching that query."
                return f"🧠 Here is what I found in my memory:\n" + "\n".join([f"- (ID: {r['id']}) {r['memory_content']}" for r in results])
            elif function_name == "forget_memory":
                if self.db.forget_memory_note(args["memory_id"]):
                    return f"🗑️ Memory with ID {args['memory_id']} has been forgotten."
                return f"⚠️ Could not find a memory with ID {args['memory_id']} to forget."
            elif function_name == "summarize_conversation_topic":
                history_snippets = self.db.search_conversation_history(args["topic"])
                if not history_snippets: return f"I couldn't find any discussion about '{args['topic']}' in our conversation history."
                
                # Use the LLM to summarize the snippets
                summary_prompt = f"Please summarize the following conversation snippets about '{args['topic']}':\n{json.dumps(history_snippets)}"
                summary_response = client.chat.completions.create(model="llama-3.3-70b-versatile", messages=[{"role": "user", "content": summary_prompt}])
                return "🔍 Here is a summary of our past discussions on that topic:\n" + summary_response.choices[0].message.content

            # System and Content Tools
            elif function_name == "execute_system_task" and self.task_executor:
                return f"✅ System task executed. Result: {self.task_executor.run_task(args['task_description'])}"
            elif function_name == "generate_image" and ImageGenMain:
                ImageGenMain(args["prompt"])
                return "🖼️ Image generated and opened."
            elif function_name == "generate_and_save_content" and Coder:
                Coder(args["topic"])
                return "✅ Content generated and saved to file."
            
            else:
                return f"⚠️ Unknown or disabled function '{function_name}'."
        except Exception as e:
            return f"❌ Error executing {function_name}: {str(e)}"

    def process_message(self, user_input: str) -> str:
        """The main cognitive cycle: Memory -> Context -> Reasoning -> Execution -> Response."""
        conversation_id = self.db.add_conversation_turn(user_input)
        try:
            # 1. Proactive Memory Retrieval (Cognitive Priming)
            relevant_memories = self._get_relevant_memories(user_input)
            short_term_history = self.db.get_recent_conversation(limit=3)

            # 2. Context Assembly
            api_messages = [
                {"role": "system", "content": self.system_instructions},
                {"role": "system", "content": f"[Relevant Long-Term Memories]\n{relevant_memories}"}
            ]
            api_messages.extend(short_term_history)
            api_messages.append({"role": "user", "content": user_input})

            # 3. Reasoning & Tool Selection
            response = client.chat.completions.create(model="llama-3.3-70b-versatile", messages=api_messages, tools=self.tools, tool_choice="auto")
            response_message = response.choices[0].message

            # 4. Execution or Direct Response
            if response_message.tool_calls:
                api_messages.append(response_message)
                tool_results = [self.execute_tool_call(tc) for tc in response_message.tool_calls]
                api_messages.extend([{"tool_call_id": tc.id, "role": "tool", "content": res} for tc, res in zip(response_message.tool_calls, tool_results)])
                
                # 5. Final Response Generation
                final_response = client.chat.completions.create(model="llama-3.3-70b-versatile", messages=api_messages)
                answer = final_response.choices[0].message.content.strip()
            else:
                answer = response_message.content.strip()

            self.db.update_assistant_response(conversation_id, answer)
            return answer

        except Exception as e:
            error_msg = f"I've encountered a critical error in my cognitive loop: {str(e)}"
            self.db.update_assistant_response(conversation_id, error_msg)
            return error_msg

# Standalone testing block
if __name__ == "__main__":
    assistant = FALCONAssistant()
    print("FALCON Cognitive Core Online. Awaiting input.")
    
    while True:
        user_input = input("\nYou: ")
        if user_input.lower() in ['exit', 'quit']:
            print("FALCON Offline.")
            break
        
        print("FALCON: ⚙️ Processing...")
        response = assistant.process_message(user_input)
        print(f"FALCON: {response}")