import asyncio
from typing import AsyncIterable, overload
from aiofile import async_open as open
from datetime import datetime
import aiohttp
import json

from livekit.agents import AutoSubscribe, JobContext, WorkerOptions, JobProcess, cli, llm
from livekit.agents.pipeline import VoicePipelineAgent
from livekit.agents.voice_assistant import VoiceAssistant
from livekit.plugins import deepgram, openai, silero
from dotenv import load_dotenv
import livekit.api
from livekit.api import UpdateParticipantRequest

import logging

load_dotenv()

logger = logging.getLogger("deepgram-stt-demo")
logger.setLevel(logging.INFO)

def prewarm(proc: JobProcess):
    proc.userdata["vad"] = silero.VAD.load()
    proc.userdata["product"] = "New mobile phone iPhone 21. 999$, mind control"
    logger.info("Set Product")

async def send_to_api(content: str, message_role: str, timestamp: str):
    async with aiohttp.ClientSession() as session:
        payload = {
            "content": content,
            "message_role": message_role,
            "timestamp": timestamp
        }
        logger.info("====== send_to_api inside=====")
        async with session.post("https://webhook.site/48f9ef4e-f686-461e-a77f-50f1882006fa", json=payload) as response:
            return await response.text()

async def send_to_story_api(messages):
    async with aiohttp.ClientSession() as session:
        payload = {
            "messages": messages,
            "illustration_style": "A medieval book illustration, without borders or frames. The illustration style mirrors that of illuminated manuscripts, with vibrant colors, intricate details, and a slightly flattened perspective that allows for a comprehensive view of the scene. Touches of gold leaf accentuate important elements, adding a magical quality to the scene. The image extends to the edges, fully immersing the viewer in the setting.",
            "main_character": "Our hero is a young man in his late twenties or early thirties with a strong build, short dark hair, and a clean-shaven face. He wears a striking red cloak over practical leather armor. His youthful yet experienced face suggests a mix of enthusiasm and earned wisdom."
        }
        logger.info("====== send_to_story_api inside=====")
        logger.info(f"Sending payload to story API: {payload}")
        async with session.post("https://storyimagegen-production.up.railway.app/process_chat", json=payload) as response:
            result = await response.json()
            logger.info(f"Received response from story API: {result}")
            return result.get('image_url')

# This function is the entrypoint for the agent.
async def entrypoint(ctx: JobContext):
    chat_messages = []
    lkapi = livekit.api.LiveKitAPI()

    async def before_tts(assistant: VoicePipelineAgent, text: str | AsyncIterable[str]):
        logger.info("====== before_tts =====")
        timestamp = datetime.now().isoformat()
        #api_queue.put_nowait((text, "agent", timestamp))
        
        # Ensure text is a string before adding to chat messages
        if isinstance(text, AsyncIterable):
            text = ''.join([chunk async for chunk in text])
        
        chat_messages.append({"role": "host", "content": text})
        logger.info(f"Added agent message to chat. Total messages: {len(chat_messages)}")
        
        #Если накоплено более 4 сообщений, вызываем новый API
        if (len(chat_messages)  ) > 1:
            # logger.info("More than 4 messages accumulated, calling story API")
            async def handle_story_api():
                chat_messages
                try:
                    image_url = await send_to_story_api(chat_messages[-1:])
                    logger.info(f"Story API called successfully. Image URL: {image_url}")

                    #chat_messages = chat_messages[4:]
                    participant = await ctx.wait_for_participant()
                    #participant = ctx.room.local_participant
                    if image_url:
                        try:
                            # logger.info("====== PUSH DATA ===== ")
                            await ctx.room.local_participant.publish_data(image_url,
                                            reliable=True,
                                            destination_identities=[participant.identity],
                                            topic="topic1")  
                            logger.info(f"====== PUSH DATA SENT to {participant.identity} ===== ")

                        except Exception as e:
                            logger.error(f"Error updating participant {participant.name} attributes: {e}")
                except Exception as e:
                    logger.error(f"Error calling Story API: {e}")
            
            # Запускаем обработку API в фоновом режиме
            asyncio.create_task(handle_story_api())
        
        return text

    async def _enrich_with_rag(assistant: VoiceAssistant, chat_ctx: llm.ChatContext):
        user_msg = chat_ctx.messages[-1]
    
    # Create an initial chat context with a system prompt
    product = ctx.proc.userdata["product"]
    logger.info("use product")
    initial_ctx = llm.ChatContext().append(
        role="system",
        # text="Отвечай только Да или Нет!",
        text = """
        Ты Synco, корпоративный ассистент.
        Твои задачи:
        - Собирать все знания о продукте и компании
        - Помогать сотрудникам компании в решении их задач
        - Быть в курсе всех новостей рынка, анализировать их и делиться сотрудникам
        """
        #         text = """
        # Ты ведущий текстовой ролевой игры.
        # Пользователь описывает свои действия, а ты описывешь реакцию игрового мира и персонажей в нём. 
        # Не придумывай за игрока его дейчствия. 

        # Игровой мир:
        # Средневековый мир, где есть люди, драконы и магия.
        # """
    )

    # Connect to the LiveKit room
    await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)

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
        before_llm_cb=_enrich_with_rag,
        before_tts_cb=before_tts,
    )

    # Start the voice assistant with the LiveKit room
    assistant.start(ctx.room)

    api_queue = asyncio.Queue()

    @assistant.on("user_speech_committed")
    def on_user_speech_committed(msg: llm.ChatMessage):
       # logger.info("====== HERE 1 =====")
        timestamp = datetime.now().isoformat()
        
        # Добавляем данные в очередь для отправки на API
        text = api_queue.put_nowait((msg.content, "user", timestamp))
        logger.info(text)
        
        # Добавляем сообщение пользователя в список сообщений чата
        chat_messages.append({"role": "player", "content": msg.content})
        #logger.info(f"Added user message to chat. Total messages: {len(chat_messages)}")

    async def send_to_api_worker():
        #logger.info("====== send_to_api_worker =====")
        while True:
            content, message_role, timestamp = await api_queue.get()
            if isinstance(content, str):
            #     logger.info(f"content is a string: {content}")
            # else:
            #     logger.info(f"content is not a string, it's a {type(content)}")
                try:
                    logger.info(f"====== send_to_api {message_role}: {content}")
                    await send_to_api(content, message_role, timestamp)
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
    await assistant.say("Приветсвую, коллеги. Я готов к работе.", allow_interruptions=True)


if __name__ == "__main__":
    # Initialize the worker with the entrypoint
    cli.run_app(WorkerOptions(
        shutdown_process_timeout=5,
        entrypoint_fnc=entrypoint, 
        prewarm_fnc=prewarm))
