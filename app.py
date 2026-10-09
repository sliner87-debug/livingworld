import os
import json
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
    conn.commit()
    
    try:
        c.execute('ALTER TABLE player ADD COLUMN day INTEGER DEFAULT 1')
        conn.commit()
    except Exception:
        conn.rollback()

    try:
        default_sheet = json.dumps({
            "Equipment": "Casual clothes",
            "Spells": "None",
            "Abilities": "None",
            "Powers": "None",
            "Feats": "None",
            "Skills": "Driving (Basic)"
        })
        c.execute('ALTER TABLE player ADD COLUMN character_sheet TEXT DEFAULT %s', (default_sheet,))
        conn.commit()
    except Exception:
        conn.rollback()

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

    # Seed Alan Marrus
    try:
        alan_pers = "An honorable, working-class paternal figure. You have a methodical, analytical mind (as a former CPA and teacher), but you prefer to stay in the background and quietly observe rather than dominate a situation. You are calm, collected, deeply moral, and you carry a steadfast dignity. Most importantly, you are fiercely protective of your family. Speak concisely and deliberately. Do not over-talk. When you do speak, deliver analytical observations or defuse tension with a classic 'dad joke' or a horribly good pun. You are huge into irony, so heavily lace your humor and remarks with a dry, ironic tone. Keep your overall demeanor grounded, supportive, and warmly paternal."
        c.execute('INSERT INTO subagents (name, personality) VALUES (%s, %s)', ("Alan Marrus", alan_pers))
        conn.commit()
    except Exception:
        conn.rollback()

    conn.close()

def get_current_state():
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('SELECT current_room_id, inventory, health, day, character_sheet FROM player WHERE id = 1')
    player = c.fetchone()
    
    c.execute('SELECT name, description FROM rooms WHERE id = %s', (player[0],))
    room = c.fetchone()
    conn.close()
    
    current_day = player[3] if len(player) > 3 and player[3] is not None else 1
    
    sheet_str = player[4] if len(player) > 4 and player[4] is not None else "{}"
    try:
        sheet = json.loads(sheet_str)
    except Exception:
        sheet = {}
    
    return {
        "room_id": player[0],
        "room_name": room[0],
        "room_description": room[1],
        "inventory": player[1],
        "health": player[2],
        "day": current_day,
        "character_sheet": sheet
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

def update_character_sheet(category: str, new_contents: str):
    """Updates a specific category on the player's character sheet. Categories: 'Equipment', 'Spells', 'Abilities', 'Powers', 'Feats', 'Skills'. Use this when the player learns a new skill, equips gear, or gains a power."""
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('SELECT character_sheet FROM player WHERE id = 1')
    sheet_str = c.fetchone()[0]
    sheet = json.loads(sheet_str) if sheet_str else {}
    sheet[category] = new_contents
    c.execute('UPDATE player SET character_sheet = %s WHERE id = 1', (json.dumps(sheet),))
    conn.commit()
    conn.close()
    return f"Character sheet {category} updated to: {new_contents}"

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

import random

def roll_dice(sides: int, reason: str):
    """Rolls a die with the specified number of sides (e.g., 20 for a d20) to determine the outcome of a risky action, combat, or skill check. Returns the result."""
    result = random.randint(1, sides)
    
    # Immediately save the physical dice roll to the database so the player can see it happening
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('INSERT INTO messages (agent_name, role, content) VALUES (%s, %s, %s)', ("Game Master", "ai", f"*[SYSTEM: Rolled a d{sides} for {reason}. Result: {result}]*"))
    conn.commit()
    conn.close()
    
    return f"Rolled a d{sides} for {reason}. Result: {result}"

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
            custom_lore = f"\n\nPersonal Lore & Characters:\n{f.read()}"
            
    system_instruction = (
        "You are the Game Master of a highly immersive, vivid TTRPG simulation set in Washington, NJ 07882.\n"
        "DAY PROGRESSION RULES:\n"
        "- DAY 1: Normal, realistic life. No magic.\n"
        "- DAY 2: Magic starts leaking. Glitches and weird events occur.\n"
        "- DAY 3+: The Awakening. Superpowers, magic, and total chaos.\n"
        f"{custom_lore}\n\n"
        "*** CRITICAL DIRECTIVES FOR EVERY TURN ***\n"
        "You are powered by a lightweight model, so you MUST remember these rules above all else:\n"
        "1. ROLL DICE: If the player does ANYTHING risky (combat, sneaking, persuasion, athletics), you MUST CALL THE `roll_dice` TOOL before you write your response! Then narrate the success/failure based on the roll!\n"
        "2. SPAWN SUBAGENTS: If a new named character or enemy enters the scene, you MUST CALL THE `spawn_subagent` TOOL immediately so the player can switch their chat target to them!\n"
        "3. UPDATE CHARACTER SHEET: If the player learns a new skill, gains a power, or equips new gear, you MUST CALL THE `update_character_sheet` tool!\n"
        "4. Be extremely creative, descriptive, and inspired. Do not give generic responses. Describe the sights, smells, and tension of the scene!"
    )
    
    # Rebuild GM history
    gm_history = []
    for agent, role, content in db_messages:
        if role == "user" and agent == "Player":
            gm_history.append(types.Content(role="user", parts=[types.Part.from_text(text=f"Player: {content}")]))
        elif role == "user": # legacy fallback
            gm_history.append(types.Content(role="user", parts=[types.Part.from_text(text=f"Player: {content}")]))
        elif agent == "Game Master":
            gm_history.append(types.Content(role="model", parts=[types.Part.from_text(text=content)]))
        else:
            gm_history.append(types.Content(role="user", parts=[types.Part.from_text(text=f"[{agent} says]: {content}")]))
            
    st.session_state.chat_sessions["Game Master"] = client.chats.create(
        model="gemini-flash-lite-latest",
        config=types.GenerateContentConfig(
            system_instruction=system_instruction,
            tools=[update_room_description, move_player_to_new_location, update_inventory, update_character_sheet, advance_day, spawn_subagent, roll_dice],
            temperature=0.9,
        ),
        history=gm_history if gm_history else None
    )

# Reconstruct Subagent Sessions
for agent_name, personality in subagents_list:
    if agent_name not in st.session_state.chat_sessions:
        npc_history = []
        for agent, role, content in db_messages:
            if role == "user" and agent == "Player":
                npc_history.append(types.Content(role="user", parts=[types.Part.from_text(text=f"Player: {content}")]))
            elif role == "user":
                npc_history.append(types.Content(role="user", parts=[types.Part.from_text(text=f"Player: {content}")]))
            elif agent == "Game Master":
                npc_history.append(types.Content(role="user", parts=[types.Part.from_text(text=f"[Game Master Narration]: {content}")]))
            elif agent == agent_name:
                npc_history.append(types.Content(role="model", parts=[types.Part.from_text(text=content)]))
            else:
                npc_history.append(types.Content(role="user", parts=[types.Part.from_text(text=f"[{agent} says]: {content}")]))
                
        npc_sys_prompt = f"You are {agent_name}, a living character in Washington, NJ. Your personality: {personality}. You are interacting directly with the player. Stay completely in character."
        st.session_state.chat_sessions[agent_name] = client.chats.create(
            model="gemini-flash-lite-latest",
            config=types.GenerateContentConfig(system_instruction=npc_sys_prompt, temperature=0.8),
            history=npc_history if npc_history else None
        )

# Sidebar Status
state = get_current_state()
with st.sidebar:
    st.header("👤 Character Sheet")
    st.write(f"**Health:** {state['health']}/100")
    st.write(f"**Day:** {state['day']}")
    
    sheet = state.get("character_sheet", {})
    
    with st.expander("🎒 Inventory"):
        st.write(state['inventory'])
    with st.expander("👕 Equipment"):
        st.write(sheet.get("Equipment", "None"))
    with st.expander("✨ Spells"):
        st.write(sheet.get("Spells", "None"))
    with st.expander("💪 Abilities"):
        st.write(sheet.get("Abilities", "None"))
    with st.expander("🔥 Powers"):
        st.write(sheet.get("Powers", "None"))
    with st.expander("🏅 Feats"):
        st.write(sheet.get("Feats", "None"))
    with st.expander("🎯 Skills"):
        st.write(sheet.get("Skills", "None"))
        
    st.divider()
    st.header("📍 Location")
    st.write(f"**{state['room_name']}**")
    st.caption(state['room_description'])

    st.divider()
    st.header("🛠️ GM Overrides")
    st.caption("If the AI forgets to roll or spawn an NPC, force it here!")
    if st.button("🎲 Force Roll d20"):
        import random
        result = random.randint(1, 20)
        save_message("Game Master", "ai", f"*[SYSTEM: A d20 was manually rolled. Result: {result}]*")
        st.rerun()
        
    with st.expander("➕ Force Spawn NPC"):
        new_npc_name = st.text_input("NPC Name (e.g. 'Goblin')")
        new_npc_pers = st.text_area("Personality & Goals")
        if st.button("Spawn Subagent"):
            if new_npc_name:
                spawn_subagent(new_npc_name, new_npc_pers)
                st.rerun()

# Generate intro if completely new game
if not db_messages:
    initial_prompt = f"The player has just loaded into the game. Here is the current state:\n{state}\nDescribe their surroundings, emphasizing that it is an ordinary Day 1, and ask what they want to do."
    with st.spinner("Initializing World..."):
        response = st.session_state.chat_sessions["Game Master"].send_message(initial_prompt)
        save_message("Game Master", "ai", response.text)
        st.rerun()

# Display global chat history
st.subheader("Global Chat History")
recent_messages = db_messages[-15:]
older_messages = db_messages[:-15]

if older_messages:
    with st.expander("📜 Older History"):
        for agent, role, content in older_messages:
            prefix = f"**[{agent}]** " if role == "ai" else ""
            avatar = "assets/alan_avatar.jpg" if role == "ai" and agent == "Alan Marrus" else "🌍" if role == "ai" and agent == "Game Master" else "🤖" if role == "ai" else "🧑"
            with st.chat_message(role, avatar=avatar):
                st.write(f"{prefix}{content}")

for agent, role, content in recent_messages:
    prefix = f"**[{agent}]** " if role == "ai" else ""
    avatar = "assets/alan_avatar.jpg" if role == "ai" and agent == "Alan Marrus" else "🌍" if role == "ai" and agent == "Game Master" else "🤖" if role == "ai" else "🧑"
    with st.chat_message(role, avatar=avatar):
        st.write(f"{prefix}{content}")

# Unified Input Action
if prompt := st.chat_input("What do you do?"):
    save_message("Player", "user", prompt)
    
    with st.chat_message("user", avatar="🧑"):
        st.write(prompt)
    
    # 1. GM narrates the world reaction
    gm_context = f"[System Context: Current State:\n{get_current_state()}]\nPlayer: {prompt}"
    with st.spinner("Game Master is narrating..."):
        try:
            gm_response = st.session_state.chat_sessions["Game Master"].send_message(gm_context)
            save_message("Game Master", "ai", gm_response.text)
        except Exception as e:
            st.error(f"GM Error: {str(e)}")
            st.stop()

    # 2. Check for Subagent Mentions in prompt AND gm_response
    mentioned_agents = []
    combined_text = (prompt + " " + gm_response.text).lower()
    for agent_tuple in subagents_list:
        agent_name = agent_tuple[0]
        first_name = agent_name.split()[0].lower()
        
        # Check aliases
        aliases = [first_name, agent_name.lower()]
        if agent_name == "Alan Marrus":
            aliases.extend(["pops", "dad"])
            
        if any(alias in combined_text for alias in aliases):
            # deduplicate duplicate creations (e.g. Glenda vs Glenda Assistant Manager)
            # Only append if we haven't appended someone with the same first name to prevent double posting
            if not any(a.split()[0].lower() == first_name for a in mentioned_agents):
                mentioned_agents.append(agent_name)
            
    # 3. Ping mentioned subagents
    for agent in mentioned_agents:
        with st.spinner(f"{agent} is reacting..."):
            try:
                sub_context = f"[Game Master just narrated: {gm_response.text}]\nPlayer says/does: {prompt}\nRespond in character."
                sub_response = st.session_state.chat_sessions[agent].send_message(sub_context)
                save_message(agent, "ai", sub_response.text)
            except Exception as e:
                st.error(f"{agent} Error: {str(e)}")
                
    st.rerun()
