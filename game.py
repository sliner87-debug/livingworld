import os
import sqlite3
import sys
from google import genai
from google.genai import types

# ---------------------------------------------------------------------------
# Database Setup
# ---------------------------------------------------------------------------
DB_FILE = "world_state.db"

def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    # Create tables
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
    # Initialize start state if empty
    c.execute('SELECT count(*) FROM rooms')
    if c.fetchone()[0] == 0:
        c.execute('''
            INSERT INTO rooms (id, name, description)
            VALUES (
                'home', 
                '12 Prosper Way', 
                'Your home at 12 Prosper Way, Washington, NJ 07882. It is a modest 1,120 sq ft house built in 2011, sitting on about half an acre. The neighborhood is quiet. Through the windows, you can see the satellite layout of the residential street.'
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

# ---------------------------------------------------------------------------
# Game Engine Tools (Function Calling for Gemini)
# ---------------------------------------------------------------------------
def update_room_description(room_id: str, new_description: str):
    """Updates the description of a room in the world state based on events."""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('UPDATE rooms SET description = ? WHERE id = ?', (new_description, room_id))
    conn.commit()
    conn.close()
    return f"Room '{room_id}' updated."

def move_player_to_new_location(new_location_id: str, location_name: str, location_description: str):
    """
    Moves the player to a new location. If the location doesn't exist yet, it is dynamically 
    created based on real-world geography (Washington, NJ).
    """
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    
    # Check if exists
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
# Main Game Loop
# ---------------------------------------------------------------------------
def main():
    if "GEMINI_API_KEY" not in os.environ:
        print("ERROR: Please set the GEMINI_API_KEY environment variable.")
        print("You can get a free key at: https://aistudio.google.com/")
        sys.exit(1)

    init_db()
    client = genai.Client()
    
    system_instruction = (
        "You are the advanced Game Master of a living, breathing text adventure simulation. "
        "The world is highly realistic, set in the present day, centered around Washington, NJ 07882. "
        "You have deep geographic knowledge of the area (satellite view accuracy) and will simulate "
        "the real-world environment, streets, buildings, and atmosphere accurately. "
        "When the user moves to a new street or location, use the `move_player_to_new_location` tool "
        "to generate that location and move them there. Keep track of items via the `update_inventory` tool. "
        "Keep your descriptions evocative, immersive, and formatted cleanly. Do NOT break character. "
        "Give the player total freedom."
    )

    # Initialize a chat session with tools
    chat = client.chats.create(
        model="gemini-3.5-flash",
        config=types.GenerateContentConfig(
            system_instruction=system_instruction,
            tools=[update_room_description, move_player_to_new_location, update_inventory],
            temperature=0.7,
        )
    )

    print("==========================================================")
    print("=             THE LIVING WORLD: WASHINGTON, NJ           =")
    print("==========================================================\n")
    print("Initializing Simulation Engine...\n")
    
    # Trigger the first description
    state = get_current_state()
    initial_prompt = f"The player has just loaded into the game. Here is the current state:\n{state}\nDescribe their surroundings and ask what they want to do."
    
    response = chat.send_message(initial_prompt)
    print(f"\n{response.text}\n")

    while True:
        try:
            user_input = input("\nWhat do you do? > ")
            if user_input.lower() in ['quit', 'exit']:
                print("Saving world state... Goodbye!")
                break
                
            state = get_current_state()
            context = f"[System Context: Current State:\n{state}]\nPlayer Action: {user_input}"
            
            response = chat.send_message(context)
            print(f"\n{response.text}")
            
        except KeyboardInterrupt:
            print("\nSaving world state... Goodbye!")
            break

if __name__ == "__main__":
    main()
