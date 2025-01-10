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
from livekit.plugins import deepgram, openai, silero , elevenlabs, cartesia

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


def prewarm(proc: JobProcess):
    proc.userdata["vad"] = silero.VAD.load()


def print_chat_messages(chat_messages):
    for message in chat_messages:
        logger.info(f"- {message.role}: {message.content[:15] if message.content and len(message.content) >= 15 else message.content}...")


async def entrypoint(ctx: JobContext):
    logger.info(f"ctx.room: {ctx.room}")

    chat_messages = []

    lkapi = livekit.api.LiveKitAPI()

    async def before_llm(assistant: VoicePipelineAgent, chat_context: str | AsyncIterable[str]):
        logger.info(f"====== before_LLM =====")

        current_user_text = chat_context.messages[-1].content if len(chat_context.messages) > 0 else None
        prev_user_text = ctx.proc.userdata.get("prev_user_text")
        logger.info(f"load prev_user_text: {prev_user_text}")
        if prev_user_text and current_user_text.startswith(prev_user_text):
            logger.info("Removing previous user text from current user text")
            current_user_text = current_user_text[len(prev_user_text):]  
            # ctx.proc.userdata["prev_user_text"] = current_user_text
        
        logger.info(current_user_text)
        if current_user_text.lstrip().lower().startswith("бустер"):
            logger.info("Start working")

            ctx.proc.userdata["prev_user_text"] = None
            logger.info(f"save prev_user_text: None")


        else:
            logger.info("No key - cancel chat")
            ctx.proc.userdata["prev_user_text"] = current_user_text if ctx.proc.userdata.get("prev_user_text") is None else ctx.proc.userdata["prev_user_text"] + current_user_text
            tmp = ctx.proc.userdata.get("prev_user_text")
            logger.info(f"save prev_user_text: {tmp}")

            # logger.info(f"new last message is {chat_context.messages}")
            return False            


    async def before_tts(assistant: VoicePipelineAgent, text: str | AsyncIterable[str]):
        logger.info("====== before_tts =====")

        full_text = []
        
        if isinstance(text, AsyncIterable):
            async def accumulate_and_yield():
                async for chunk in text:
                    full_text.append(chunk)
                    # logger.info(f"chunk: {chunk}")
                    yield chunk
                
                # После завершения всех чанков, можно залогировать полный текст
                logger.info(f"full text: {''.join(full_text)}")
            return accumulate_and_yield()
        else:
            return text


        # logger.info(f"len text: text: {text}")
        # if isinstance(text, AsyncIterable):
        #      logger.info(f"AsyncIterable")
        #      #text = ''.join([chunk async for chunk in text])
        # else:
        #     logger.info(f"not . {text}")     
        
        # return text

    # Connect to the LiveKit room
    await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)

    logger.info(f"====== ctx.room = {ctx.room} =====")
        
    initial_ctx = llm.ChatContext().append(
        role="system",
        text = """
        Ты корпоративный помощник. Твоя задача помогать сотрудникам в их паботе. Отвечать на запросы и выполнять поручения.
        """
        # + " Отвечай только на Английском языке.""
    )
    # voice = elevenlabs.Voice(
    #             id=os.getenv("ELEVENLABS_VOICE_ID"),
    #             name="Alice",
    #             category="standard",
    #             )

    # tts = elevenlabs.TTS(
    #         # model_id="eleven_multilingual_v2",
    #         model_id="eleven_flash_v2_5",
    #         voice = elevenlabs.Voice(
    #             id=os.getenv("ELEVENLABS_VOICE_ID"),
    #             name="Alice",
    #             category="standard",
    #             ),
    #         api_key=os.getenv("ELEVENLABS_API_KEY"),
    #     )
    tts = cartesia.TTS(
        speed = 0.5,
        voice = "da05e96d-ca10-4220-9042-d8acef654fa9"
    )

    assistant = VoiceAssistant(
        vad=ctx.proc.userdata["vad"],
        stt=deepgram.STT(
            language="ru"
        ),
        llm=openai.LLM(
            model="gpt-4o-mini",
        ),
        # tts=openai.TTS(),
        tts = tts,
    
        chat_ctx=initial_ctx,
        before_llm_cb=before_llm,
        before_tts_cb=before_tts,

    )

    # Start the voice assistant with the LiveKit room
    assistant.start(ctx.room)

    participant = await ctx.wait_for_participant()
    logger.info(f"Get participant: {participant}")

    @assistant.on("agent_speech_committed")
    def on_agent_speech_committed(msg: llm.ChatMessage):

        logger.info("====== on_agent_speech_committed =====")
        print_chat_messages(assistant.chat_ctx.messages)




    @assistant.on("user_speech_committed")
    def on_user_speech_committed(msg: llm.ChatMessage):
        logger.info("====== user_speech_committed ===")
        logger.info(f"User message: {msg.content}")

        # Добавляем сообщение пользователя в список сообщений чата
        chat_messages.append({"role": "player", "content": msg.content})
        logger.info(f"Added player message to chat. Total messages: {len(chat_messages)}")

    async def on_session_end():
        logger.info("====== on_session_end. time to generate Preview =====")
        

    ctx.add_shutdown_callback(on_session_end)  

    await asyncio.sleep(1)

    # Greets the user with an initial message
    await assistant.say("Привет! Я корпоративный помощник, Бустер. Я отвечаю когда вы обратитесь ко мне по имени.")


if __name__ == "__main__":
    # Initialize the worker with the entrypoint
    cli.run_app(WorkerOptions(
        shutdown_process_timeout=5,
        entrypoint_fnc=entrypoint, 
        prewarm_fnc=prewarm))
