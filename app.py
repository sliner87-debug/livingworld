import os
import sqlite3
import streamlit as st
from google import genai
from google.genai import types

# ---------------------------------------------------------------------------
# Database Setup
# ---------------------------------------------------------------------------
DB_FILE = "world_state.db"

def init_db():
    conn = sqlite3.connect(DB_FILE)
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
            health INTEGER
        )
    ''')
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
            INSERT INTO player (id, current_room_id, inventory, health)
            VALUES (1, 'home', 'Smartphone, Wallet, House Keys', 100)
        ''')
    conn.commit()
    conn.close()

def get_current_state():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('SELECT current_room_id, inventory, health FROM player WHERE id = 1')
    player = c.fetchone()
    
    c.execute('SELECT name, description FROM rooms WHERE id = ?', (player[0],))
    room = c.fetchone()
    conn.close()
    
    return {
        "room_id": player[0],
        "room_name": room[0],
        "room_description": room[1],
        "inventory": player[1],
        "health": player[2]
    }

# Tools
def update_room_description(room_id: str, new_description: str):
    """Updates the description of a room in the world state based on events."""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('UPDATE rooms SET description = ? WHERE id = ?', (new_description, room_id))
    conn.commit()
    conn.close()
    return f"Room '{room_id}' updated."

def move_player_to_new_location(new_location_id: str, location_name: str, location_description: str):
    """Moves the player to a new location. Dynamically creates it if it doesn't exist."""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('SELECT id FROM rooms WHERE id = ?', (new_location_id,))
    if not c.fetchone():
        c.execute('INSERT INTO rooms (id, name, description) VALUES (?, ?, ?)', 
                  (new_location_id, location_name, location_description))
    c.execute('UPDATE player SET current_room_id = ? WHERE id = 1', (new_location_id,))
    conn.commit()
    conn.close()
    return f"Player moved to {location_name} ({new_location_id})."

def update_inventory(new_inventory_contents: str):
    """Updates the player's inventory when they pick up or drop an item."""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('UPDATE player SET inventory = ? WHERE id = 1', (new_inventory_contents,))
    conn.commit()
    conn.close()
    return f"Inventory updated to: {new_inventory_contents}"

# ---------------------------------------------------------------------------
# Streamlit App
# ---------------------------------------------------------------------------
st.set_page_config(page_title="Living World", page_icon="🌍", layout="centered")
st.title("🌍 The Living World: Washington, NJ")

# Setup DB
init_db()

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

# Setup GenAI Client & Chat Session
if "chat_session" not in st.session_state:
    client = genai.Client(api_key=api_key)
    system_instruction = (
        "You are the advanced Game Master of a living, breathing text adventure simulation. "
        "The world is highly realistic, set in the present day, centered around Washington, NJ 07882. "
        "You have deep geographic knowledge of the area and will simulate the real-world environment accurately. "
        "Use tools to update the world state based on player actions. "
        "Keep your descriptions evocative and immersive. Give the player total freedom."
    )
    st.session_state.chat_session = client.chats.create(
        model="gemini-3.5-flash",
        config=types.GenerateContentConfig(
            system_instruction=system_instruction,
            tools=[update_room_description, move_player_to_new_location, update_inventory],
            temperature=0.7,
        )
    )
    
    # Generate intro
    state = get_current_state()
    initial_prompt = f"The player has just loaded into the game. Here is the current state:\n{state}\nDescribe their surroundings and ask what they want to do."
    with st.spinner("Initializing World..."):
        response = st.session_state.chat_session.send_message(initial_prompt)
        st.session_state.messages = [{"role": "ai", "content": response.text}]

# Sidebar Status
state = get_current_state()
with st.sidebar:
    st.header("👤 Player Status")
    st.write(f"**Health:** {state['health']}/100")
    st.write(f"**Inventory:** {state['inventory']}")
    st.divider()
    st.header("📍 Location")
    st.write(f"**{state['room_name']}**")
    st.caption(state['room_description'])

# Display chat history
for msg in st.session_state.messages:
    if msg["role"] == "user":
        st.chat_message("user").write(msg["content"])
    else:
        st.chat_message("assistant").write(msg["content"])

# Input Action
if prompt := st.chat_input("What do you do?"):
    st.session_state.messages.append({"role": "user", "content": prompt})
    st.chat_message("user").write(prompt)
    
    context = f"[System Context: Current State:\n{get_current_state()}]\nPlayer Action: {prompt}"
    
    with st.spinner("The world reacts..."):
        try:
            response = st.session_state.chat_session.send_message(context)
            st.session_state.messages.append({"role": "ai", "content": response.text})
            st.rerun()
        except Exception as e:
            st.error(f"Error: {str(e)}")
