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

class GameData(BaseModel):
    world_description: str
    character_description: str
    character_appearance: Optional[str]
    image_style_prompt: Optional[str]
    latest_summary: Optional[str]
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
    #proc.userdata["product"] = "New mobile phone iPhone 21. 999$, mind control"
    #logger.info("Set Product")

async def send_to_api(content: str, message_role: str, game_id: str, turn_id: str | None = None, user_text: str | None = None):
    async with aiohttp.ClientSession() as session:
        logger.info(f"====== send_to_api inside {message_role} =====")
        if message_role == "host":
            payload = {
                "game_id": game_id,
                "player_text": user_text,
                "gm_response": content
            }        
            async with session.post(f"{os.getenv('STORY_API_URL')}/turns", json=payload) as response:
                response_json = await response.json()
                logger.info(f"API Response: {response_json}")
                return response_json.get('id')  # Возвращаем id из ответа
        # elif turn_id:
        #     logger.info(f"====== send_to_api not user - {message_role}: {content}")
        #     payload = {
        #         "gm_response": content
        #     }        
        #     async with session.put(f"{os.getenv('STORY_API_URL')}/turns/{turn_id}", json=payload) as response:
        #         response_json = await response.json()
        #         logger.info(f"API Response: {response_json}")
        #         return turn_id


async def save_next_turn_api(user_text: str, gm_text: str, game_id: str):
    async with aiohttp.ClientSession() as session:
        payload = {
            "game_id": game_id,
            "player_text": user_text,
            "gm_response": gm_text
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
            "messages": messages,
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
            return result.get('image_url')

async def handle_imagegen_api(chat_messages, last_turn_id, ctx, game_data):
    try:
        image_url = await send_to_imageGen_api(chat_messages[-1:], last_turn_id, game_data)
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

def print_chat_messages(chat_messages):
    for message in chat_messages:
        logger.info(f"- {message.role}: {message.content[:15] if message.content and len(message.content) >= 15 else message.content}...")


async def entrypoint(ctx: JobContext):
    logger.info(f"ctx.room: {ctx.room}")

    chat_messages = []
    current_user_text = None
    lkapi = livekit.api.LiveKitAPI()

    async def before_llm(assistant: VoicePipelineAgent, chat_context: str | AsyncIterable[str]):
        logger.info("====== before_LLM =====")
        current_user_text = chat_context.messages[-1].content if len(chat_context.messages) > 0 else None
        logger.info(current_user_text)

    async def before_tts(assistant: VoicePipelineAgent, text: str | AsyncIterable[str]):
        # if (len(chat_messages)) > 0:
            # nonlocal last_turn_id
        logger.info("====== before_tts =====")
        logger.info(f"chat_messages: {len(assistant.chat_ctx.messages)}")
        # print_chat_messages(assistant.chat_ctx.messages)

        # Ensure text is a string before adding to chat messages
        if isinstance(text, AsyncIterable):
            logger.info(f"AsyncIterable")
            text = ''.join([chunk async for chunk in text])
        
        chat_messages.append({
            "role": "host", 
            "content": text,
            
        })
    
        # user_text = current_user_text #chat_messages[-1]["content"] if len(chat_messages) > 1 else None
        # logger.info(f"User text in tts : {user_text[:15] if user_text and len(user_text) >= 15 else user_text}...")
        # logger.info(f"GM Text  : {text[:15] if text and len(text) >= 15 else text}...")
        
        # asyncio.create_task( save_next_turn_api(user_text, text, str(game_data.game.id)) )
        # #api_queue.put_nowait((text, "host", user_text))

        # logger.info(f"Added agent message to chat. Total messages: {len(chat_messages)}")
        
        #Если накоплено более 1 сообщений, вызываем новый API
        
        # Запускаем обработку API в фоновом режиме
        asyncio.create_task(handle_imagegen_api(chat_messages, "", ctx, game_data))
        
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
        
        # Send turn to API
        if len(assistant.chat_ctx.messages) > 2:
            user_text = assistant.chat_ctx.messages[-2].content
            gm_text = assistant.chat_ctx.messages[-1].content
            asyncio.create_task( save_next_turn_api(user_text, gm_text, str(game_data.game.id)) )




    @assistant.on("user_speech_committed")
    def on_user_speech_committed(msg: llm.ChatMessage):
        logger.info("====== user_speech_committed ===")
        # Добавляем данные в очередь для отправки на API
        # text = api_queue.put_nowait((msg.content, "user"))
        # logger.info(text)
        
        # Добавляем сообщение пользователя в список сообщений чата
        chat_messages.append({"role": "player", "content": msg.content})
        logger.info(f"Added player message to chat. Total messages: {len(chat_messages)}")

    # async def send_to_api_worker():
    #     # nonlocal last_turn_id
    #     logger.info(f"====== send_to_api_worker knows game_id {game_id} and last_turn_id {last_turn_id} =====")
    #     while True:
    #         content, message_role, user_text = await api_queue.get()
    #         logger.info(f"====== from api_queue {message_role}: {content}")
    #         if isinstance(content, str):
    #             try:
    #                 logger.info(f"====== send_to_api {message_role}: {content}")
    #                 turn_id = await send_to_api(content, message_role,  game_id, last_turn_id, user_text)
    #                 if turn_id:
    #                     last_turn_id = turn_id  # Сохраняем id хода
    #                     logger.info(f"Saved turn_id: {last_turn_id}")
    #             except Exception as e:
    #                 logger.error(f"Error sending data to API: {e}")
    #             finally:
    #                 api_queue.task_done()

    # api_task = asyncio.create_task(send_to_api_worker())

    # async def finish_queue():
    #     logger.info("====== finish_queue =====")
    #     # await api_queue.join()
    #     # try:
    #     #     await api_task
    #     # except asyncio.CancelledError:
    #     #     pass

    async def on_session_end():
        logger.info("====== on_session_end. time to generate Preview =====")
        

    # ctx.add_shutdown_callback(finish_queue)      
    ctx.add_shutdown_callback(on_session_end)  

    await asyncio.sleep(1)

    # Greets the user with an initial message
    await assistant.say("Начнём?", allow_interruptions=False)


if __name__ == "__main__":
    # Initialize the worker with the entrypoint
    cli.run_app(WorkerOptions(
        shutdown_process_timeout=5,
        entrypoint_fnc=entrypoint, 
        prewarm_fnc=prewarm))
