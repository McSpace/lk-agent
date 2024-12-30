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
from livekit.plugins import deepgram, openai, silero
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
    last_turn_number: int
    created_at: datetime
    updated_at: datetime

class GameData(BaseModel):
    world_description: str
    character_description: str
    latest_summary: str
    turns: List[str]
    game: Game
    user_lang: str

async def get_game_data(game_id: str) -> Optional[GameData]:
    """Fetch game data from Story API"""
    try:
        async with aiohttp.ClientSession() as session:
            url = f"{os.getenv('STORY_APY_URL')}/games/{game_id}"
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
    #proc.userdata["product"] = "New mobile phone iPhone 21. 999$, mind control"
    #logger.info("Set Product")

async def send_to_api(content: str, message_role: str, timestamp: str, game_id: str, turn_id: str | None = None):
    async with aiohttp.ClientSession() as session:
        logger.info("====== send_to_api inside=====")
        if message_role == "user":
            payload = {
                "game_id": game_id,
                "player_text": content
            }        
            async with session.post(f"{os.getenv('STORY_APY_URL')}/turns", json=payload) as response:
                response_json = await response.json()
                logger.info(f"API Response: {response_json}")
                return response_json.get('id')  # Возвращаем id из ответа
        else:
            payload = {
                "gm_response": content
            }        
            async with session.put(f"{os.getenv('STORY_APY_URL')}/turns/{turn_id}", json=payload) as response:
                response_json = await response.json()
                logger.info(f"API Response: {response_json}")
                return response_json.get('gm_response')  # Возвращаем id из ответа


async def send_to_imageGen_api(messages, turn_id):
    async with aiohttp.ClientSession() as session:
        payload = {
            "pic_id": turn_id,
            "messages": messages,
            "illustration_style": "A medieval book illustration, without borders or frames. The illustration style mirrors that of illuminated manuscripts, with vibrant colors, intricate details, and a slightly flattened perspective that allows for a comprehensive view of the scene. Touches of gold leaf accentuate important elements, adding a magical quality to the scene. The image extends to the edges, fully immersing the viewer in the setting.",
            "main_character": "Our hero is a young man in his late twenties or early thirties with a strong build, short dark hair, and a clean-shaven face. He wears a striking red cloak over practical leather armor. His youthful yet experienced face suggests a mix of enthusiasm and earned wisdom."
        }
        logger.info("====== send_to_imageGen_api inside=====")
        logger.info(f"Sending payload to story API: {payload}")
        async with session.post("https://storyimagegen-production.up.railway.app/process_chat", json=payload) as response:
            result = await response.json()
            logger.info(f"Received response from story API: {result}")
            return result.get('image_url')
            
async def handle_imagegen_api(chat_messages, last_turn_id, ctx):
    try:
        image_url = await send_to_imageGen_api(chat_messages[-1:], last_turn_id)
        logger.info(f"Story API called successfully. Image URL: {image_url}")

        participant = await ctx.wait_for_participant()
        if image_url:
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
async def entrypoint(ctx: JobContext):
    logger.info(f"ctx.room: {ctx.room}")

    chat_messages = []
    last_turn_id = None
    lkapi = livekit.api.LiveKitAPI()

    async def before_tts(assistant: VoicePipelineAgent, text: str | AsyncIterable[str]):
        nonlocal last_turn_id
        logger.info("====== before_tts =====")
        logger.info(f"last_turn_id: {last_turn_id}")
        timestamp = datetime.now().isoformat()
        
        # Ensure text is a string before adding to chat messages
        if isinstance(text, AsyncIterable):
            text = ''.join([chunk async for chunk in text])
        
        chat_messages.append({
            "role": "host", 
            "content": text,
            "turn_id": last_turn_id  # Добавляем id хода к сообщению
        })
        logger.info(f"Added agent message to chat. Total messages: {len(chat_messages)}")
        
        #Если накоплено более 1 сообщений, вызываем новый API
        if (len(chat_messages)) > 1:
            # Запускаем обработку API в фоновом режиме
            asyncio.create_task(handle_imagegen_api(chat_messages, last_turn_id, ctx))
        
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
            Не придумывай за игрока его дейчствия.

            Игровой мир:
            {game_data.world_description}

            Персонаж игрока:
            {game_data.character_description}

            
            {f"Текущее состояние игры: {game_data.latest_summary}"  if game_data.latest_summary else ""}
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
            Средневековый мир, где есть люди, драконы и магия.
            """
        )

    assistant = VoiceAssistant(
        vad=ctx.proc.userdata["vad"],
        stt=deepgram.STT(
            language="ru"
        ),
        llm=openai.LLM(
            model="gpt-4o-mini",
        ),
        tts=openai.TTS(),
        chat_ctx=initial_ctx,
        before_tts_cb=before_tts,
    )

    # Start the voice assistant with the LiveKit room
    assistant.start(ctx.room)

    api_queue = asyncio.Queue()

    participant = await ctx.wait_for_participant()
    logger.info(f"Get participant: {participant}")

    @assistant.on("user_speech_committed")
    def on_user_speech_committed(msg: llm.ChatMessage):
        timestamp = datetime.now().isoformat()
        
        # Добавляем данные в очередь для отправки на API
        text = api_queue.put_nowait((msg.content, "user", timestamp))
        logger.info(text)
        
        # Добавляем сообщение пользователя в список сообщений чата
        chat_messages.append({"role": "player", "content": msg.content})

    async def send_to_api_worker():
        nonlocal last_turn_id
        logger.info(f"====== send_to_api_worker knows game_id {game_id} =====")
        while True:
            content, message_role, timestamp = await api_queue.get()
            if isinstance(content, str):
                try:
                    logger.info(f"====== send_to_api {message_role}: {content}")
                    turn_id = await send_to_api(content, message_role, timestamp, game_id)
                    if turn_id:
                        last_turn_id = turn_id  # Сохраняем id хода
                        logger.info(f"Saved turn_id: {last_turn_id}")
                except Exception as e:
                    logger.error(f"Error sending data to API: {e}")
                finally:
                    api_queue.task_done()

    api_task = asyncio.create_task(send_to_api_worker())

    async def finish_queue():
        await api_queue.join()
        try:
            await api_task
        except asyncio.CancelledError:
            pass

    ctx.add_shutdown_callback(finish_queue)        

    await asyncio.sleep(1)

    # Greets the user with an initial message
    await assistant.say("Алло! Кто это?", allow_interruptions=True)


if __name__ == "__main__":
    # Initialize the worker with the entrypoint
    cli.run_app(WorkerOptions(
        shutdown_process_timeout=5,
        entrypoint_fnc=entrypoint, 
        prewarm_fnc=prewarm))
