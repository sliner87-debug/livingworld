import os
import streamlit as st
import psycopg2
from google import genai
from google.genai import types

# ---------------------------------------------------------------------------
# Database Setup
# ---------------------------------------------------------------------------
def get_db_connection():
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        try:
            db_url = st.secrets["DATABASE_URL"]
        except Exception:
            pass
    if not db_url:
        st.warning("Please configure your DATABASE_URL in Streamlit secrets.")
        st.stop()
    
    conn = psycopg2.connect(db_url)
    return conn

def init_db():
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS rooms (
            id TEXT PRIMARY KEY,
            name TEXT,
            description TEXT
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS player (
            id INTEGER PRIMARY KEY,
            current_room_id TEXT,
            inventory TEXT,
            health INTEGER,
            day INTEGER
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS messages (
            id SERIAL PRIMARY KEY,
            agent_name TEXT,
            role TEXT,
            content TEXT
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS subagents (
            name TEXT PRIMARY KEY,
            personality TEXT
        )
    ''')
    
    try:
        c.execute('ALTER TABLE player ADD COLUMN day INTEGER DEFAULT 1')
    except Exception:
        pass

    c.execute('SELECT count(*) FROM rooms')
    if c.fetchone()[0] == 0:
        c.execute('''
            INSERT INTO rooms (id, name, description)
            VALUES (
                'home', 
                '12 Prosper Way', 
                'Your home at 12 Prosper Way, Washington, NJ 07882. It is a modest 1,120 sq ft house built in 2011, sitting on about half an acre. The neighborhood is quiet. Through the windows, you can see the residential street.'
            )
        ''')
        c.execute('''
            INSERT INTO player (id, current_room_id, inventory, health, day)
            VALUES (1, 'home', 'Smartphone, Wallet, House Keys', 100, 1)
        ''')
    conn.commit()
    conn.close()

def get_current_state():
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('SELECT current_room_id, inventory, health, day FROM player WHERE id = 1')
    player = c.fetchone()
    
    c.execute('SELECT name, description FROM rooms WHERE id = %s', (player[0],))
    room = c.fetchone()
    conn.close()
    
    current_day = player[3] if len(player) > 3 and player[3] is not None else 1
    
    return {
        "room_id": player[0],
        "room_name": room[0],
        "room_description": room[1],
        "inventory": player[1],
        "health": player[2],
        "day": current_day
    }

def save_message(agent_name, role, content):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('INSERT INTO messages (agent_name, role, content) VALUES (%s, %s, %s)', (agent_name, role, content))
    conn.commit()
    conn.close()

def get_all_messages():
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('SELECT agent_name, role, content FROM messages ORDER BY id ASC')
    msgs = c.fetchall()
    conn.close()
    return msgs

def get_subagents():
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('SELECT name, personality FROM subagents')
    agents = c.fetchall()
    conn.close()
    return agents

# Tools
def update_room_description(room_id: str, new_description: str):
    """Updates the description of a room in the world state based on events."""
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('UPDATE rooms SET description = %s WHERE id = %s', (new_description, room_id))
    conn.commit()
    conn.close()
    return f"Room '{room_id}' updated."

def move_player_to_new_location(new_location_id: str, location_name: str, location_description: str):
    """Moves the player to a new location. Dynamically creates it if it doesn't exist."""
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('SELECT id FROM rooms WHERE id = %s', (new_location_id,))
    if not c.fetchone():
        c.execute('INSERT INTO rooms (id, name, description) VALUES (%s, %s, %s)', 
                  (new_location_id, location_name, location_description))
    c.execute('UPDATE player SET current_room_id = %s WHERE id = 1', (new_location_id,))
    conn.commit()
    conn.close()
    return f"Player moved to {location_name} ({new_location_id})."

def update_inventory(new_inventory_contents: str):
    """Updates the player's inventory when they pick up or drop an item."""
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('UPDATE player SET inventory = %s WHERE id = 1', (new_inventory_contents,))
    conn.commit()
    conn.close()
    return f"Inventory updated to: {new_inventory_contents}"

def advance_day():
    """Advances the game to the next day when the player sleeps or enough time passes."""
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('UPDATE player SET day = day + 1 WHERE id = 1')
    c.execute('SELECT day FROM player WHERE id = 1')
    new_day = c.fetchone()[0]
    conn.commit()
    conn.close()
    return f"Time has passed. It is now Day {new_day}."

def spawn_subagent(character_name: str, personality_and_goals: str):
    """Spawns a new independent AI Subagent for an NPC or enemy. Use this when the player engages a specific character in deep conversation or combat."""
    conn = get_db_connection()
    c = conn.cursor()
    try:
        c.execute('INSERT INTO subagents (name, personality) VALUES (%s, %s)', (character_name, personality_and_goals))
        conn.commit()
    except Exception:
        pass # Already exists
    conn.close()
    return f"Subagent '{character_name}' spawned successfully. The player can now talk to them directly."

# ---------------------------------------------------------------------------
# Streamlit App
# ---------------------------------------------------------------------------
st.set_page_config(page_title="Living World", page_icon="🌍", layout="centered")
st.title("🌍 The Living World: Washington, NJ")

# Check DB Connection
try:
    init_db()
except Exception as e:
    st.error(f"Database Connection Error: Make sure your password is correct in the DATABASE_URL secret! Error details: {e}")
    st.stop()

# Check API Key
api_key = os.environ.get("GEMINI_API_KEY")
if not api_key:
    try:
        api_key = st.secrets["GEMINI_API_KEY"]
    except Exception:
        pass

if not api_key:
    st.warning("Please enter your Gemini API Key to play.")
    api_key = st.text_input("Gemini API Key", type="password")
    if api_key:
        os.environ["GEMINI_API_KEY"] = api_key
        st.rerun()
    else:
        st.stop()

# Load Database Messages
db_messages = get_all_messages()
subagents_list = get_subagents()

# Setup GenAI Client & Chat Sessions
client = genai.Client(api_key=api_key)

if "chat_sessions" not in st.session_state:
    st.session_state.chat_sessions = {}

# Reconstruct Game Master Session
if "Game Master" not in st.session_state.chat_sessions:
    custom_lore = ""
    if os.path.exists("lore.txt"):
        with open("lore.txt", "r", encoding="utf-8") as f:
            custom_lore = f"\n\nPersonal Lore & Characters to include in the world:\n{f.read()}"
            
    system_instruction = (
        "You are the Game Master of a dynamic, living simulation set in Washington, NJ 07882. "
        "The world begins completely normal and realistic. "
        "However, there is a strict progression of world events based on the current Day:\n"
        "- DAY 1: Modern day, completely realistic. No magic.\n"
        "- DAY 2: Odd events begin. Magic slowly starts leaking into the world. Electronics glitch.\n"
        "- DAY 3 AND BEYOND: The Awakening. People rapidly manifest powers (superheroes, villains, mages, psions). The world devolves into chaotic superhero/fantasy dynamics.\n"
        "Use the `advance_day` tool when time passes. "
        "Use the `spawn_subagent` tool whenever a unique NPC or enemy appears so the player can talk to them directly!"
        + custom_lore
    )
    
    # Rebuild GM history
    gm_history = []
    for agent, role, content in db_messages:
        if agent == "Game Master":
            r = "user" if role == "user" else "model"
            gm_history.append(types.Content(role=r, parts=[types.Part.from_text(text=content)]))
            
    st.session_state.chat_sessions["Game Master"] = client.chats.create(
        model="gemini-flash-latest",
        config=types.GenerateContentConfig(
            system_instruction=system_instruction,
            tools=[update_room_description, move_player_to_new_location, update_inventory, advance_day, spawn_subagent],
            temperature=0.7,
        ),
        history=gm_history if gm_history else None
    )

# Reconstruct Subagent Sessions
for agent_name, personality in subagents_list:
    if agent_name not in st.session_state.chat_sessions:
        npc_history = []
        for agent, role, content in db_messages:
            if agent == agent_name:
                r = "user" if role == "user" else "model"
                npc_history.append(types.Content(role=r, parts=[types.Part.from_text(text=content)]))
                
        npc_sys_prompt = f"You are {agent_name}, a living character in Washington, NJ. Your personality: {personality}. You are interacting directly with the player. Stay completely in character."
        st.session_state.chat_sessions[agent_name] = client.chats.create(
            model="gemini-flash-latest",
            config=types.GenerateContentConfig(system_instruction=npc_sys_prompt, temperature=0.8),
            history=npc_history if npc_history else None
        )

# Sidebar Status & Router
state = get_current_state()
with st.sidebar:
    st.header("🗣️ Conversation Target")
    agent_options = ["Game Master"] + [a[0] for a in subagents_list]
    selected_agent = st.selectbox("Who are you talking to?", agent_options)
    
    st.divider()
    st.header("👤 Player Status")
    st.write(f"**Health:** {state['health']}/100")
    st.write(f"**Inventory:** {state['inventory']}")
    st.write(f"**Day:** {state['day']}")
    st.divider()
    st.header("📍 Location")
    st.write(f"**{state['room_name']}**")
    st.caption(state['room_description'])

# Generate intro if completely new game
if not db_messages:
    initial_prompt = f"The player has just loaded into the game. Here is the current state:\n{state}\nDescribe their surroundings, emphasizing that it is an ordinary Day 1, and ask what they want to do."
    with st.spinner("Initializing World..."):
        response = st.session_state.chat_sessions["Game Master"].send_message(initial_prompt)
        save_message("Game Master", "ai", response.text)
        st.rerun()

# Display global chat history (last 10 messages)
st.subheader("Global Chat History")
recent_messages = db_messages[-10:]
older_messages = db_messages[:-10]

if older_messages:
    with st.expander("📜 Older History"):
        for agent, role, content in older_messages:
            prefix = f"**[{agent}]** " if role == "ai" else ""
            with st.chat_message(role):
                st.write(f"{prefix}{content}")

for agent, role, content in recent_messages:
    prefix = f"**[{agent}]** " if role == "ai" else ""
    with st.chat_message(role):
        st.write(f"{prefix}{content}")

# Input Action
if prompt := st.chat_input(f"Message {selected_agent}..."):
    save_message(selected_agent, "user", prompt)
    
    with st.chat_message("user"):
        st.write(prompt)
    
    context = f"[System Context: Current State:\n{get_current_state()}]\nPlayer: {prompt}"
    
    with st.spinner(f"{selected_agent} is thinking..."):
        try:
            chat = st.session_state.chat_sessions[selected_agent]
            response = chat.send_message(context)
            save_message(selected_agent, "ai", response.text)
            st.rerun()
        except Exception as e:
            st.error(f"Error: {str(e)}")
