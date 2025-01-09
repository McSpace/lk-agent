import asyncio
from typing import AsyncIterable, overload
from aiofile import async_open as open
from datetime import datetime
import aiohttp
import json
import os
import dotenv


from livekit.agents import AutoSubscribe, JobContext, WorkerOptions, JobProcess, cli, llm
from livekit.agents.pipeline import VoicePipelineAgent
from livekit.agents.voice_assistant import VoiceAssistant
from livekit.plugins import deepgram, openai, silero , elevenlabs
from dotenv import load_dotenv
import livekit.api
from livekit.api import UpdateParticipantRequest

import logging
from uuid import UUID
from pydantic import BaseModel
from typing import Dict, List, Optional

load_dotenv()

logger = logging.getLogger("deepgram-stt-demo")
logger.setLevel(logging.INFO)

# Models for Story API
class Game(BaseModel):
    title: str
    settings: Dict
    id: UUID
    world_id: UUID
    user_id: UUID
    character_id: UUID
    status: str
    created_at: datetime
    updated_at: datetime

class GameSummary(BaseModel):
    id: UUID
    turn_number: int
    summary_text: str

class GameData(BaseModel):
    world_description: str
    character_description: str
    character_appearance: Optional[str]
    image_style_prompt: Optional[str]
    latest_summary: Optional[GameSummary]
    game: Game
    user_lang: str

async def get_game_data(game_id: str) -> Optional[GameData]:
    """Fetch game data from Story API"""
    try:
        async with aiohttp.ClientSession() as session:
            url = f"{os.getenv('STORY_API_URL')}/games/{game_id}"
            async with session.get(url) as response:
                if response.status == 200:
                    data = await response.json()
                    return GameData.parse_obj(data)
                logger.error(f"Failed to fetch game data: {response.status}")
                return None
    except Exception as e:
        logger.error(f"Error fetching game data: {e}")
        return None

def prewarm(proc: JobProcess):
    proc.userdata["vad"] = silero.VAD.load()

async def save_next_turn_api(user_text: str, gm_text: str, game_id: str, image_url: str, pic_prompt: str):
    async with aiohttp.ClientSession() as session:
        payload = {
            "game_id": game_id,
            "player_text": user_text,
            "gm_response": gm_text,
            "image_url": image_url,
            "pic_prompt": pic_prompt
        } 
        logger.info("====== save_next_turn_api inside=====")
        logger.info(f"Sending payload to story API: {payload}")
        async with session.post(f"{os.getenv('STORY_API_URL')}/turns", json=payload) as response:
            response_json = await response.json()
            logger.info(f"API Response: {response_json}")
            return 
async def send_to_imageGen_api(messages, turn_id, game_data: GameData):
    async with aiohttp.ClientSession() as session:
        payload = {
            "pic_id": turn_id,
            "chat_history": messages,
            "illustration_style": game_data.image_style_prompt, #"A medieval book illustration, without borders or frames. The illustration style mirrors that of illuminated manuscripts, with vibrant colors, intricate details, and a slightly flattened perspective that allows for a comprehensive view of the scene. Touches of gold leaf accentuate important elements, adding a magical quality to the scene. The image extends to the edges, fully immersing the viewer in the setting.",
            "main_character":  game_data.character_appearance # "Our hero is a young man in his late twenties or early thirties with a strong build, short dark hair, and a clean-shaven face. He wears a striking red cloak over practical leather armor. His youthful yet experienced face suggests a mix of enthusiasm and earned wisdom."
        }
        logger.info("====== send_to_imageGen_api inside=====")
        logger.info(f"Sending payload to story API: {payload}")
        async with session.post("https://storyimagegen-production.up.railway.app/process_chat", 
                                timeout=60,
                                json=payload
                                ) as response:
            result = await response.json()
            logger.info(f"Received response from story API: {result}")
            return result

async def handle_imagegen_api(gm_text, last_turn_id, ctx, game_data):
    try:
        generator_result = await send_to_imageGen_api(gm_text, last_turn_id, game_data)
        image_url = generator_result.get('image_url') if generator_result else None
        image_prompt = generator_result.get('illustration_prompt') if generator_result else None
        logger.info(f"Story API called successfully. Image URL: {image_url}")

        participant = await ctx.wait_for_participant()
        if image_url:
            ctx.proc.userdata["pic_url"] = image_url
            ctx.proc.userdata["pic_prompt"] = image_prompt
            logger.info(f"====== SET PIC URL: {image_url} ===== ") 
            try:
                await ctx.room.local_participant.publish_data(image_url,
                                reliable=True,
                                destination_identities=[participant.identity],
                                topic="topic1")  
                logger.info(f"====== PUSH DATA SENT to {participant.identity} ===== ")

            except Exception as e:
                logger.error(f"Error updating participant {participant.name} attributes: {e}")
    except Exception as e:
        logger.error(f"Error calling Story API: {e}")

# This function is the entrypoint for the agent.

def print_chat_messages(chat_messages):
    for message in chat_messages:
        logger.info(f"- {message.role}: {message.content[:15] if message.content and len(message.content) >= 15 else message.content}...")


async def entrypoint(ctx: JobContext):
    logger.info(f"ctx.room: {ctx.room}")

    chat_messages = []
    # current_user_text = None
    # prev_user_text = ""
    lkapi = livekit.api.LiveKitAPI()

    async def before_llm(assistant: VoicePipelineAgent, chat_context: str | AsyncIterable[str]):
        logger.info(f"====== before_LLM =====")

        current_user_text = chat_context.messages[-1].content if len(chat_context.messages) > 0 else None
        prev_user_text = ctx.proc.userdata["prev_user_text"]
        if prev_user_text and current_user_text.startswith(prev_user_text):
            logger.info("Removing previous user text from current user text")
            current_user_text = current_user_text[len(prev_user_text):]  
        
        logger.info(current_user_text)
        if current_user_text.lower()[:6] == "хорошо":
            logger.info("User cancelled chat")

            ctx.proc.userdata["prev_user_text"] = current_user_text

            logger.info(f"new last message is {chat_context.messages}")
            return False
        else:
            ctx.proc.userdata["prev_user_text"] = None
            logger.info("User did not cancel chat")


    async def before_tts(assistant: VoicePipelineAgent, text: str | AsyncIterable[str]):
        logger.info("====== before_tts =====")
        # logger.info(f"chat_messages: {len(assistant.chat_ctx.messages)}")
        logger.info(f"len text: text: {text}")
        if isinstance(text, AsyncIterable):
             logger.info(f"AsyncIterable")
             #text = ''.join([chunk async for chunk in text])
        else:
            logger.info(f"not AsyncIterable. {text}")     

        # # Ensure text is a string before adding to chat messages
        # if isinstance(text, AsyncIterable):
        #     logger.info(f"AsyncIterable")
        #     text = ''.join([chunk async for chunk in text])
        
        # chat_messages.append({
        #     "role": "host", 
        #     "content": text,
            
        # })
        
        # # if len(chat_messages) > 2:
        # # Запускаем обработку API в фоновом режиме
        # asyncio.create_task(handle_imagegen_api(text, "", ctx, game_data))
        
        return text

    # Connect to the LiveKit room
    await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)

    logger.info(f"====== ctx.room = {ctx.room} =====")
    
    # Load game data from story-API   
    game_id = ctx.room.name
    
    # Fetch game data
    game_data = await get_game_data(game_id)
    if game_data:
        logger.info(f"Successfully loaded game data for game {game_id}")
        initial_ctx = llm.ChatContext().append(
            role="system",
            text = f"""
            Ты ведущий текстовой ролевой игры.
            Пользователь описывает свои действия, а ты описывешь реакцию игрового мира и персонажей в нём. 
            Не придумывай за игрока его дейчствия. Используй своё воображение и креативность.
            Отвечай на '{game_data.user_lang}' языке.

            Игровой мир:
            {game_data.world_description}

            Персонаж игрока:
            {game_data.character_description}

            
            {f"Текущее состояние игры: {game_data.latest_summary.summary_text}"  if game_data.latest_summary else ""}
            """
        )
    else:
        logger.error(f"Failed to load game data for game {game_id}, using default context")
        initial_ctx = llm.ChatContext().append(
            role="system",
            text = """
            Ты ведущий текстовой ролевой игры.
            Пользователь описывает свои действия, а ты описывешь реакцию игрового мира и персонажей в нём. 
            Не придумывай за игрока его дейчствия. 

            Игровой мир:
            Средневековый мир, где есть люди и магия.
            """
        )
    voice = elevenlabs.Voice(
                id=os.getenv("ELEVENLABS_VOICE_ID"),
                name="Alice",
                category="standard",
                )
    assistant = VoiceAssistant(
        vad=ctx.proc.userdata["vad"],
        stt=deepgram.STT(
            language=game_data.user_lang
        ),
        llm=openai.LLM(
            model="gpt-4o-mini",
        ),
        # tts=openai.TTS(),
        tts = elevenlabs.TTS(
            model_id="eleven_multilingual_v2",
            voice=voice,
            api_key=os.getenv("ELEVENLABS_API_KEY"),
            # language=game_data.user_lang
        ),
        chat_ctx=initial_ctx,
        before_llm_cb=before_llm,
        before_tts_cb=before_tts,

    )

    # Start the voice assistant with the LiveKit room
    assistant.start(ctx.room)

    api_queue = asyncio.Queue()

    participant = await ctx.wait_for_participant()
    logger.info(f"Get participant: {participant}")

    @assistant.on("agent_speech_committed")
    def on_agent_speech_committed(msg: llm.ChatMessage):

        logger.info("====== on_agent_speech_committed =====")
        print_chat_messages(assistant.chat_ctx.messages)

        pic_url = ctx.proc.userdata.get("pic_url")
        pic_prompt = ctx.proc.userdata.get("pic_prompt")
        logger.info(f"====== CHECK PIC URL: {pic_url} ===== ") 
        
        # Send turn to API
        if len(assistant.chat_ctx.messages) > 2:
            user_text = assistant.chat_ctx.messages[-2].content
            gm_text = assistant.chat_ctx.messages[-1].content
            asyncio.create_task( save_next_turn_api(user_text, gm_text, str(game_data.game.id), pic_url, pic_prompt) )




    @assistant.on("user_speech_committed")
    def on_user_speech_committed(msg: llm.ChatMessage):
        logger.info("====== user_speech_committed ===")
        logger.info(f"User message: {msg.content}")
        # Добавляем данные в очередь для отправки на API
        # text = api_queue.put_nowait((msg.content, "user"))
        # logger.info(text)
        
        # Добавляем сообщение пользователя в список сообщений чата
        chat_messages.append({"role": "player", "content": msg.content})
        logger.info(f"Added player message to chat. Total messages: {len(chat_messages)}")

    async def on_session_end():
        logger.info("====== on_session_end. time to generate Preview =====")
        if len(assistant.chat_ctx.messages) > 2:
            async with aiohttp.ClientSession() as session:
                payload = {} 
                logger.info("====== save_next_turn_api inside=====")
                logger.info(f"Sending payload to story API: {payload}")
                async with session.post(f"{os.getenv('STORY_API_URL')}/summary/{game_id}/generate", json=payload) as response:
                    response_json = await response.json()
                    logger.info(f"summary generate API Response: {response_json}")
                    return 
        else:
            logger.info("====== Not enough messages to generate summary =====")
        

    ctx.add_shutdown_callback(on_session_end)  

    await asyncio.sleep(1)

    # Greets the user with an initial message
    #await assistant.say(game_data.latest_summary.summary_text if game_data.latest_summary else "Начнём?", allow_interruptions=True)


if __name__ == "__main__":
    # Initialize the worker with the entrypoint
    cli.run_app(WorkerOptions(
        shutdown_process_timeout=5,
        entrypoint_fnc=entrypoint, 
        prewarm_fnc=prewarm))
