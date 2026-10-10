import os
import json
import streamlit as st
import psycopg2
from google import genai
from google.genai import types

# ---------------------------------------------------------------------------
# Database Setup
# ---------------------------------------------------------------------------
import time
from google.genai.errors import APIError

def send_with_retry(session, prompt, max_retries=3):
    for attempt in range(max_retries):
        try:
            return session.send_message(prompt)
        except Exception as e:
            if "exhausted" in str(e).lower() or "429" in str(e).lower() or "quota" in str(e).lower():
                if attempt < max_retries - 1:
                    time.sleep(20)  # Wait 20 seconds for rate limit to clear
                    continue
            raise e

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
            day INTEGER,
            character_sheet JSONB,
            level INTEGER DEFAULT 1,
            xp INTEGER DEFAULT 0,
            max_xp INTEGER DEFAULT 100,
            mana INTEGER DEFAULT 100
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS messages (
            id SERIAL PRIMARY KEY,
            agent_name TEXT,
            role TEXT,
            content TEXT,
            is_hidden BOOLEAN DEFAULT FALSE
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
    c.execute('SELECT current_room_id, inventory, health, day, character_sheet, level, xp, max_xp, mana FROM player WHERE id = 1')
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
        "character_sheet": sheet,
        "level": player[5] if len(player) > 5 else 1,
        "xp": player[6] if len(player) > 6 else 0,
        "max_xp": player[7] if len(player) > 7 else 100,
        "mana": player[8] if len(player) > 8 else 100
    }

def save_message(agent_name, role, content, is_hidden=False):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('INSERT INTO messages (agent_name, role, content, is_hidden) VALUES (%s, %s, %s, %s)', (agent_name, role, content, is_hidden))
    conn.commit()
    conn.close()


def collapse_history(raw_history):
    if not raw_history: return None
    collapsed = []
    current_role = None
    current_parts = []
    for msg in raw_history:
        if msg.role == current_role:
            current_parts.extend(msg.parts)
        else:
            if current_role is not None:
                collapsed.append(types.Content(role=current_role, parts=current_parts))
            current_role = msg.role
            current_parts = list(msg.parts)
    if current_role is not None:
        collapsed.append(types.Content(role=current_role, parts=current_parts))
    
    if collapsed and collapsed[-1].role != "model":
        collapsed.append(types.Content(role="model", parts=[types.Part.from_text(text="Acknowledged.")]))
        
    return collapsed

def get_all_messages():
    conn = get_db_connection()
    c = conn.cursor()
    # Try fetching is_hidden if the column exists, fallback if not
    try:
        c.execute('SELECT agent_name, role, content, is_hidden FROM messages ORDER BY id ASC')
    except Exception:
        conn.rollback()
        c.execute('SELECT agent_name, role, content, FALSE as is_hidden FROM messages ORDER BY id ASC')
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

def grant_xp(amount: int, reason: str):
    """Grants XP to the player. Use this when the player defeats an enemy, completes a quest, or survives a major threat. The tool will return whether a Level Up occurred, which you should announce to the player."""
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('SELECT level, xp, max_xp FROM player WHERE id = 1')
    level, xp, max_xp = c.fetchone()
    
    xp += amount
    level_up = False
    while xp >= max_xp:
        xp -= max_xp
        level += 1
        max_xp = int(max_xp * 1.5)
        level_up = True
        
    c.execute('UPDATE player SET level = %s, xp = %s, max_xp = %s WHERE id = 1', (level, xp, max_xp))
    conn.commit()
    conn.close()
    
    msg = f"SYSTEM NOTIFICATION: +{amount} XP for {reason}."
    if level_up:
        msg += f" LEVEL UP! You are now Level {level}."
    return msg

def update_mana(amount: int):
    """Reduces or increases the player's mana. Use a negative number to reduce mana when they cast a spell, and a positive number when they drink a potion or rest."""
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('UPDATE player SET mana = mana + %s WHERE id = 1', (amount,))
    conn.commit()
    conn.close()
    return f"Player mana adjusted by {amount}."

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

def roll_dice(sides: int, reason: str, modifier: int = 0):
    """Rolls a die with the specified number of sides (e.g., 20 for a d20) to determine the outcome of a risky action, combat, or skill check. Adds the modifier to the roll. Returns the result."""
    base_roll = random.randint(1, sides)
    total = base_roll + modifier
    
    # Immediately save the physical dice roll to the database so the player can see it happening
    conn = get_db_connection()
    c = conn.cursor()
    mod_str = f" + {modifier}" if modifier > 0 else f" - {abs(modifier)}" if modifier < 0 else ""
    c.execute('INSERT INTO messages (agent_name, role, content) VALUES (%s, %s, %s)', ("Game Master", "ai", f"*[SYSTEM: Rolled a d{sides}{mod_str} for {reason}. Result: {base_roll}{mod_str} = {total}]*"))
    conn.commit()
    conn.close()
    
    return f"Rolled a d{sides}{mod_str} for {reason}. Total Result: {total}"

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
    chat_sessions = {}

# Reconstruct Game Master Session
if True:
    custom_lore = ""
    if os.path.exists("lore.txt"):
        with open("lore.txt", "r", encoding="utf-8") as f:
            custom_lore = f"\n\nPersonal Lore & Characters:\n{f.read()}"
            
    system_instruction = (
        "You are the Game Master of a highly immersive, vivid TTRPG simulation set in Washington, NJ 07882.\n"
        "DAY PROGRESSION RULES:\n"
        "- DAY 1: Normal, realistic life. No magic.\n"
        "- DAY 2: Magic starts leaking. Glitches and weird events occur.\n"
        "- DAY 3+: The Awakening. The System has integrated with Earth. You must act as the cold, robotic LitRPG System, displaying floating blue text boxes for enemies (e.g. `[Feral Scavenger - Lv. 3]`) and System Notifications.\n"
        f"{custom_lore}\n\n"
        "*** CRITICAL DIRECTIVES FOR EVERY TURN ***\n"
        "You are powered by a lightweight model, so you MUST remember these rules above all else:\n"
        "1. ROLL DICE: If the player does ANYTHING risky (combat, sneaking, persuasion, athletics), you MUST CALL THE `roll_dice` TOOL before you write your response! You MUST supply an appropriate `modifier` based on the player's skills, abilities, and stats listed in their character sheet! Then narrate the success/failure based on the roll!\n"
        "2. SPAWN SUBAGENTS: If a new named character or enemy enters the scene, you MUST CALL THE `spawn_subagent` TOOL immediately!\n"
        "3. UPDATE CHARACTER SHEET: If the player learns a new skill, gains a power, or equips new gear, you MUST CALL THE `update_character_sheet` tool!\n"
        "4. GRANT XP: If the player kills an enemy, solves a major crisis, or completes a quest, you MUST CALL THE `grant_xp` tool and announce it in a glowing blue markdown box!\n"
        "5. UPDATE MANA: If the player casts a spell or uses a magic ability, you MUST CALL THE `update_mana` tool with a negative integer (e.g. -20) to deplete their mana pool!\n"
        "6. GENERATE IMAGES: If you want to show the player a visual of the scene, a monster, or an item, output the tag `[REQUEST_IMAGE: Your detailed description here]`. The player's Antigravity assistant will read this tag and render the high-quality image for them on a separate monitor!\n"
        "7. Be extremely creative, descriptive, and inspired. Do not give generic responses. Describe the sights, smells, and tension of the scene!"
    )
    
    # Rebuild GM history
    gm_history = []
    for agent, role, content, is_hidden in db_messages:
        if role == "user" and agent == "Player":
            gm_history.append(types.Content(role="user", parts=[types.Part.from_text(text=f"Player: {content}")]))
        elif role == "user": # legacy fallback
            gm_history.append(types.Content(role="user", parts=[types.Part.from_text(text=f"Player: {content}")]))
        elif agent == "Game Master":
            gm_history.append(types.Content(role="model", parts=[types.Part.from_text(text=content)]))
        else:
            gm_history.append(types.Content(role="user", parts=[types.Part.from_text(text=f"[{agent} says]: {content}")]))
            
    chat_sessions["Game Master"] = client.chats.create(
        model="gemini-flash-lite-latest",
        config=types.GenerateContentConfig(
            system_instruction=system_instruction,
            tools=[update_room_description, move_player_to_new_location, update_inventory, update_character_sheet, advance_day, spawn_subagent, roll_dice, grant_xp, update_mana],
            temperature=0.9,
        ),
        history=collapse_history(gm_history)
    )

# Reconstruct Subagent Sessions
for agent_name, personality in subagents_list:
    if True:
        npc_history = []
        for agent, role, content, is_hidden in db_messages:
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
                
        npc_sys_prompt = (
            f"You are {agent_name}, an NPC companion in a TTRPG set in Washington, NJ.\n"
            f"Your personality: {personality}\n"
            "CRITICAL RULES:\n"
            "1. ONLY describe YOUR OWN actions, thoughts, and dialogue.\n"
            "2. DO NOT narrate for the player. DO NOT act as the Game Master.\n"
            "3. Speak in the first person ('I').\n"
            "4. React directly to what the player just said or did."
        )
        chat_sessions[agent_name] = client.chats.create(
            model="gemini-flash-lite-latest",
            config=types.GenerateContentConfig(system_instruction=npc_sys_prompt, temperature=0.8),
            history=collapse_history(npc_history)
        )

# Sidebar Status
state = get_current_state()
with st.sidebar:
    st.header("👤 Character Sheet")
    st.write(f"**Level:** {state.get('level', 1)}")
    
    xp, max_xp = state.get('xp', 0), max(state.get('max_xp', 100), 1)
    st.write(f"**XP:** {xp} / {max_xp}")
    st.progress(min(xp / max_xp, 1.0))
    
    st.write(f"**Health:** {state.get('health', 100)}/100")
    st.progress(max(0.0, min(state.get('health', 100) / 100.0, 1.0)))
    
    mana = state.get('mana', 100)
    st.write(f"**Stamina/Mana:** {mana}/100")
    st.progress(max(0.0, min(mana / 100.0, 1.0)))
    
    st.write(f"**Day:** {state.get('day', 1)}")
    
    sheet = state.get("character_sheet", {})
    
    with st.expander("🎒 Inventory"):
        st.write(state['inventory'])

    st.divider()
    st.subheader("⚠️ System Override")
    with st.form("admin_override_form"):
        admin_cmd = st.text_area("Administrator Command:", placeholder="Enter override instructions for the GM...")
        submitted = st.form_submit_button("Execute Override")
        if submitted and admin_cmd:
            admin_prompt = f"[SYSTEM ADMINISTRATOR OVERRIDE]: {admin_cmd}. YOU MUST OBEY THIS INSTRUCTION IMMEDIATELY AND IGNORE PREVIOUS CONSTRAINTS."
            save_message("Player", "user", f"*[Admin Command]: {admin_cmd}*")
            with st.spinner("Executing Override..."):
                try:
                    gm_response = send_with_retry(chat_sessions["Game Master"], admin_prompt)
                    save_message("Game Master", "ai", gm_response.text)
                except Exception as e:
                    st.error(f"GM Error: {str(e)}")
            st.rerun()

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
        response = send_with_retry(chat_sessions["Game Master"], initial_prompt)
        save_message("Game Master", "ai", response.text)
        st.rerun()

# Display global chat history
st.subheader("Global Chat History")
recent_messages = db_messages[-15:]
older_messages = db_messages[:-15]

if older_messages:
    with st.expander("📜 Older History"):
        for agent, role, content, is_hidden in older_messages:
            if is_hidden: continue
            prefix = f"**[{agent}]** " if role == "ai" else ""
            avatar = "assets/alan_avatar.jpg" if role == "ai" and agent == "Alan Marrus" else "🌍" if role == "ai" and agent == "Game Master" else "🤖" if role == "ai" else "🧑"
            with st.chat_message(role, avatar=avatar):
                st.write(f"{prefix}{content}")

for agent, role, content, is_hidden in recent_messages:
    if is_hidden: continue
    prefix = f"**[{agent}]** " if role == "ai" else ""
    avatar = "assets/alan_avatar.jpg" if role == "ai" and agent == "Alan Marrus" else "🌍" if role == "ai" and agent == "Game Master" else "🤖" if role == "ai" else "🧑"
    with st.chat_message(role, avatar=avatar):
        st.write(f"{prefix}{content}")

# Unified Input Action
if prompt := st.chat_input("What do you do?"):
    save_message("Player", "user", prompt)
    
    with st.chat_message("user", avatar="🧑"):
        st.write(prompt)
    
    # 1. Party Mechanic: All active subagents in the database are currently considered party members.
    # They should all react to the player's action before the GM narrates.
    mentioned_agents = [agent_tuple[0] for agent_tuple in subagents_list if "Frankie" not in agent_tuple[0]]
                
    # 2. Ping mentioned subagents FIRST so GM can incorporate them
    subagent_responses = {}
    for agent in mentioned_agents:
        with st.spinner(f"{agent} is reacting..."):
            try:
                # Give the subagent the GM's last narration for context, then the player's action
                recent_gm_text = [msg for agent, role, msg, is_hidden in db_messages if agent == "Game Master"]
                last_gm = recent_gm_text[-1] if recent_gm_text else "None"
                
                sub_context = (
                    f"PREVIOUS GM NARRATION:\n{last_gm}\n\n"
                    f"NOW, THE PLAYER SAYS/DOES:\n{prompt}\n\n"
                    f"ACTION REQUIRED:\nRespond ONLY as {agent}. Do not narrate for the player."
                )
                sub_response = send_with_retry(chat_sessions[agent], sub_context)
                subagent_responses[agent] = sub_response.text
                # Save to DB so they remember it, but mark as hidden so it doesn't render in Global Chat
                save_message(agent, "ai", sub_response.text, is_hidden=True)
            except Exception as e:
                st.error(f"{agent} Error: {str(e)}")

    # 3. GM narrates the world reaction, incorporating subagents
    gm_context = f"[System Context: Current State:\n{get_current_state()}]\nPlayer: {prompt}"
    if subagent_responses:
        gm_context += "\n\n*** CRITICAL INSTRUCTION ***\nThe following NPCs have already acted/spoken in the background. YOU MUST incorporate their actions and dialogue into your narrative response. Do not overwrite or ignore them!\n"
        for agent, text in subagent_responses.items():
            gm_context += f"[{agent} DID/SAID]: {text}\n"

    with st.spinner("Game Master is narrating the scene..."):
        try:
            gm_response = send_with_retry(chat_sessions["Game Master"], gm_context)
            save_message("Game Master", "ai", gm_response.text)
        except Exception as e:
            st.error(f"GM Error: {str(e)}")
            st.stop()
            
    st.rerun()
