import os
import json
from flask import Flask, request, jsonify
from openai import OpenAI
from supabase import create_client
from dotenv import load_dotenv
from flask_cors import CORS

import random
from datetime import datetime
import pytz

load_dotenv()

supabase_url = os.getenv("SUPABASE_URL")
supabase_key = os.getenv("SUPABASE_ANON_KEY")
supabase = create_client(supabase_url, supabase_key)

# from openai import OpenAI
client = OpenAI(
    api_key = os.getenv("OPENAI_KEY")
)

app = Flask(__name__)
CORS(app, origins=["http://localhost:3000"])

# Load JSON data
# with open("components.json", "r") as file:
#     components = json.load(file)


@app.route('/api/submit')
def home():
    return "Starting flask backend"

#generates a persona with name, personality, event -------------------------------------------------------------------------------------------------------
@app.route('/api/generate', methods=['GET'])
def generate():
    try:
        event = request.args.get('event')

        response = supabase.table("personas").select("*").eq("event", event).execute()
        listOfPersonas = ""
        
        if response.data:
            for persona in response.data:
                listOfPersonas += (persona.get("name") + ", ")

        prompt = "Give me only the name of one major character who can be a person, inanimate object, etc. from the historical event: " + event + " who is not in the list: " + listOfPersonas
        stream = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "You are a helpful assistant for giving a name of a character from historical events."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=10,
            temperature=0.9,
            stream=True,
        )

        name = ""
        for chunk in stream:
            if chunk.choices[0].delta.content is not None:
                name += chunk.choices[0].delta.content


        prompt2 = "Describe the personality of: " + name + " from the historical event: " + event + " in 30 words or less in a first person perspective"
        stream2 = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "You are a helpful assistant for giving a short description of a character's personality from historical events."},
                {"role": "user", "content": prompt2}
            ],
            max_tokens=50,
            temperature=0.9,
            stream=True,
        )

        personality = ""
        for chunk in stream2:
            if chunk.choices[0].delta.content is not None:
                personality += chunk.choices[0].delta.content

        # send this to supabase
        response = (
            supabase.table("personas")
            .insert({"name": name, "personality": personality, "event": event})
            .execute()
        )

        # fetch the persona's ID and return it
        fetchPersonaData = supabase.table("personas").select("*").eq("name", name).eq("personality", personality).eq("event", event).execute()
        print(fetchPersonaData)
        id = fetchPersonaData.data[0].get("id")

        return jsonify({"id": id, "name": name, "personality": personality, "event": event})
    except Exception as e:
        # Print the full error message
        print(f"An error occurred when calling the OpenAI API: {e}")
        return jsonify({"error": "An error occurred when processing your request."}), 500



@app.route("/api/chat", methods=['GET', 'POST'])
def chat(): 
    persona_id = request.args.get("persona_id") # persona id

    major_points = ["beginning", "climbing action", "falling action", "conclusion"]
    # persona_id = "800142"

    chat_history_text = "" # basic text
    chat_history_start = "You are going continue telling story of "

    # find all instances of chat history related to a persona_id
    response = supabase.table("chat_history").select("*").eq("persona_id", persona_id).execute()
    
    subevent_number = len(response.data) + 1 # Label as 1,2,3,4 depending on how many chats were previously generated

    # fetch a chat history if provided a story_Id
    if subevent_number > 0:
        chat_history_start = "You already told the story of "
        # get the chat history
        for chat in response.data:
            chat_history_text += chat.get("message")
    else:
        chat_history_text = ""

    # fetch persona based on id
    response = supabase.table("personas").select("*").eq("id", persona_id).execute()

    if response:
        persona = response.data[0] # return first of the list

        prompt = f"""
        You are a storyteller with a {persona.get("personality")} personality, narrating the events of {persona.get("event")}.
        The story begins as follows:

        "{chat_history_start}"

        Continue the narrative from this point, focusing on the perspective of {persona.get("name")}, and ensure the continuation is unique and at different a point further in time in the event of {persona.get("event")} without repeating any previous content or phrases. Try a different introduction besides "You already told the story of..." Limit your response to 150 words.
        """
        stream = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are a helpful assistant who retells a historical event in the perspective of a given character with a given personality."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=200,
            temperature=0.9,
            stream=True,
        )

        story = ""
        for chunk in stream:
            if chunk.choices[0].delta.content is not None:
                story += chunk.choices[0].delta.content

        # Generate a Title for the subevent:
        prompt3 = "Based on this story: " + story + ", which is related to the historical event: " + persona.get("event") + ", give it a short title."
        stream3 = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are a helpful assistant who gives a story a title."},
                {"role": "user", "content": prompt3}
            ],
            max_tokens=20,
            temperature=0.9,
            stream=True,
        )

        subevent_title = ""
        for chunk in stream3:
            if chunk.choices[0].delta.content is not None:
                subevent_title += chunk.choices[0].delta.content
        
        # Create a new row in database for chat history
        supabaseResponse = (
            supabase.table("chat_history")
            .insert({"persona_id": persona_id, "message": story, "is_user_input": False, "subevent_number": subevent_number, "subevent_title": subevent_title})
            .execute()
        )
    return jsonify({"id": subevent_number - 1, "title": subevent_title, "content": story, "event": persona.get("event")})

# Generate more of the story based on persona id and user input
@app.route("/api/chatWithUser", methods=['GET', 'POST'])
def generation(): 

    # part of story is already made 
    persona_id = request.args.get("persona_id") # persona id
    input = request.args.get("input")
    

    chat_history_start = ""

    # find all instances of chat history related to a persona_id
    response = supabase.table("chat_history").select("*").eq("persona_id", persona_id).execute()
    
    subevent_number = len(response.data) + 1

    # fetch a chat history if provided a story_Id
    if subevent_number > 0:
        chat_history_start = "You already told the story of "
        # get the chat history
        for chat in response.data:
            chat_history_text += chat.get("message")
    else:
        chat_history_text = ""

    # fetch persona based on id
    response = supabase.table("personas").select("*").eq("id", persona_id).execute()

    if response:
        persona = response.data[0] # return first of the list

        prompt = f"""
        Answer the user's prompt {input}
        You are a storyteller with a {persona.get("personality")} personality, who was narrating the events of {persona.get("event")} but the user asked a question for you to answer.
        The history of the conversation leading up to the question is:
        "{chat_history_start}"

        Answer the user's question, focusing on the perspective of {persona.get("name")}. Limit your response to 150 words.
        """
        stream = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are a helpful assistant who retells a historical event in the perspective of a given character with a given personality."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=200,
            temperature=0.9,
            stream=True,
        )

        for chunk in stream:
            if chunk.choices[0].delta.content is not None:
                yield(chunk.choice[0].delta.content)

        return generation(), {"Content-Type": "text/plain"}
            
    # since the user's questions are not part of the story, do not add to history
    # return jsonify({"content": story})



# Generate a list of characteristic of the character (id) -------------------------------------------------------------------------------------------------------
@app.route('/api/generate_character', methods=['POST'])
def generate_character():
    try:
        # Get the character name from the request
        data = request.get_json()
        character_name = data.get("character_name")
        event_name = data.get("event_name")

        if not character_name or not event_name:
            return jsonify({"error": "Character name and event name are required"}), 400

        # Generate character description
        prompt = f"""
        You are designing {character_name} from the event {event_name}.
        Every character must include the following components: HEAD, NOSE, EYEBROW, TOP, BOTTOM. 
        The following components are optional: HAIR, FACIALHAIR, HAT, GLASSES.

        Focus only on the character's literal, physical appearance. Do not consider symbolic meanings, metaphors, or cultural associations when selecting components.

        For each component, choose the most appropriate option based on the descriptions below:

        HEAD: 41: Face with mouth
        NOSE: 42: A normal Nose
        EYEBROW: 5: Neutral eyebrows
        TOP: 43: Long sleeve shirt, 44: Short sleeve shirt, 45: Sleeveless shirt with a slight flair at the bottom similar to a dress
        BOTTOM: 1: Long pants, 2: Short pants, 3: A short skirt that flares outwards
        HAIR (optional): 24: Generic short hairstyle for males, 29: Mid-length hairstyle for women, with bangs
        FACIALHAIR (optional): 16: Horseshoe mustache, 18: Mustache and beard
        HAT (optional): 35: Crown, 36: Baseball cap
        GLASSES (optional): 23: Glasses

        Give me only an array of selected IDs that best match the character.
        """
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "You are a helpful assistant that generates the characteristics of a character and matches those characteristics with the corresponding IDs of the components from the provided list."},
                {"role": "user", "content": prompt}
                ],
            max_tokens=200,
            temperature=0.7,
            stream=True,
        )

        result = ""
        for chunk in response:
            if chunk.choices[0].delta.content is not None:
                result += chunk.choices[0].delta.content

        selected_ids = json.loads(result)  # Expecting OpenAI to return a JSON array of IDs

        # Return the array of IDs to the frontend
        return jsonify(selected_ids)

    except json.JSONDecodeError:
        return jsonify({"error": "Failed to decode the response from OpenAI"}), 500
    except Exception as e:
        print(f"An error occurred: {e}")
        return jsonify({"error": "An unexpected error occurred"}), 500    

# @app.route('/test/supabase', methods=['GET'])
# def test_supabase():
#     # add data
#     # response_1 = (
#     #     supabase.table("test_table")
#     #     .insert({"name": "Sample Entry again?"})
#     #     .execute()
#     # )

#     # fetch data
#     response = supabase.table("test_table").select("*").eq("id", 1).execute()

#     return response.data

    
    


if __name__ == '__main__':
    app.run(debug=True)