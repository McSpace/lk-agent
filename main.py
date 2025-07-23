import asyncio
from typing import AsyncIterable
from aiofile import async_open as open
from datetime import datetime
import aiohttp
import os
import dotenv

from livekit.agents import AutoSubscribe, JobContext, WorkerOptions, JobProcess, cli, llm
from livekit.agents import VoiceAgent, TranscriptionAgent, TTSAgent
from livekit.plugins import deepgram, openai, silero, cartesia
from livekit.plugins import turn_detector
from dotenv import load_dotenv
import livekit.api

import logging
from uuid import UUID
from pydantic import BaseModel
from typing import Dict, Optional

load_dotenv()

logger = logging.getLogger("rpg-agent")
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
    intro: Optional[str]
    latest_summary: Optional[GameSummary]
    game: Game
    user_lang: str

async def get_game_data(game_id: str) -> Optional[GameData]:
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
    proc.userdata["turn_det"] = turn_detector.TurnDetector()

async def send_to_imageGen_api(messages, turn_id, game_data: GameData):
    async with aiohttp.ClientSession() as session:
        payload = {
            "pic_id": turn_id,
            "chat_history": messages[-1],
            "illustration_style": game_data.image_style_prompt,
            "main_character": game_data.character_appearance
        }
        logger.info("Sending image generation payload: %s", payload)
        async with session.post("https://storyimagegen-production.up.railway.app/process_chat", 
                                timeout=60,
                                json=payload) as response:
            return await response.json()

async def save_next_turn_api(user_text: str, gm_text: str, game_id: str, image_url: str, image_prompt: str):
    async with aiohttp.ClientSession() as session:
        payload = {
            "game_id": game_id,
            "player_text": user_text,
            "gm_response": gm_text,
            "image_url": image_url,
            "image_prompt": image_prompt
        }
        logger.info("Saving turn to API: %s", payload)
        await session.post(f"{os.getenv('STORY_API_URL')}/turns", json=payload)

async def handle_imagegen_api(gm_text, last_turn_id, ctx, game_data, agent):
    try:
        logger.info(
            "handle_imagegen_api called, gm_text length=%d, messages=%d",
            len(gm_text) if gm_text else 0,
            len(agent.chat_ctx.messages),
        )
        result = await send_to_imageGen_api(agent.chat_ctx.messages, last_turn_id, game_data)
        logger.info("ImageGen API result: %s", result)
        image_url = result.get('image_url')
        image_prompt = result.get('illustration_prompt')

        if image_url:
            ctx.proc.userdata["pic_url"] = image_url
            ctx.proc.userdata["image_prompt"] = image_prompt
            participant = await ctx.wait_for_participant()
            await ctx.room.local_participant.publish_data(
                image_url,
                reliable=True,
                destination_identities=[participant.identity],
                topic="topic1",
            )

            if len(agent.chat_ctx.messages) > 2:
                user_text = agent.chat_ctx.messages[-1].content
                await save_next_turn_api(
                    user_text,
                    gm_text,
                    str(game_data.game.id),
                    image_url,
                    image_prompt,
                )
                logger.info("Turn saved to API")
            else:
                logger.info(
                    "Not enough messages to save turn: %d",
                    len(agent.chat_ctx.messages),
                )
        else:
            logger.info("ImageGen API returned no image_url, skipping turn save")
    except Exception as e:
        logger.error(f"ImageGen API error: {e}")

async def entrypoint(ctx: JobContext):
    await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)

    game_id = ctx.room.name
    game_data = await get_game_data(game_id)

    user_lang_code = "en"
    user_lang = "English"
    if game_data:
        if game_data.user_lang == "ru":
            user_lang = "Russian"
            user_lang_code = "ru"
        elif game_data.user_lang == "nl":
            user_lang = "Dutch"
            user_lang_code = "nl"

    initial_ctx = llm.ChatContext().append(
        role="system",
        text=f"""
        Ты ведущий текстовой ролевой игры.
        Пользователь описывает свои действия, а ты описываешь реакцию мира.
        Отвечай на '{user_lang}' языке.

        Игровой мир:
        {game_data.world_description if game_data else 'Средневековый мир с магией'}

        Персонаж:
        {game_data.character_description if game_data else 'Неизвестный герой'}

        {f'Текущее состояние: {game_data.latest_summary.summary_text}' if game_data and game_data.latest_summary else ''}
        """
    )

    tts = cartesia.TTS(
        speed=0.5 if user_lang_code == "ru" else (0.8 if user_lang_code == "nl" else 1),
        voice="da05e96d-ca10-4220-9042-d8acef654fa9" if user_lang_code == "ru" else (
            "9e8db62d-056f-47f3-b3b6-1b05767f9176" if user_lang_code == "nl" else "da05e96d-ca10-4220-9042-d8acef654fa9"
        ),
        language=user_lang_code
    )

    agent = VoiceAgent(
        stt=deepgram.STT(language=user_lang_code),
        tts=tts,
        llm=openai.LLM(model="o4-mini"),
        chat_ctx=initial_ctx,
    )

    async def before_llm(agent: VoiceAgent, chat_ctx: AsyncIterable[str] | str):
        logger.info("Before LLM callback triggered")
        for msg in agent.chat_ctx.messages:
            logger.info(f"{msg.role}: {msg.content}")

    async def before_tts(agent: VoiceAgent, text: AsyncIterable[str] | str):
        logger.info("Before TTS callback triggered")

        full_text = []
        if isinstance(text, AsyncIterable):
            async def stream():
                async for chunk in text:
                    full_text.append(chunk)
                    yield chunk
                final_text = ''.join(full_text)
                logger.info(f"Final text: {final_text}")
                logger.info(
                    "Triggering handle_imagegen_api with final_text length %d",
                    len(final_text),
                )
                asyncio.create_task(handle_imagegen_api(final_text, "", ctx, game_data, agent))
            return stream()
        else:
            logger.info(
                "Triggering handle_imagegen_api with text length %d",
                len(text) if text else 0,
            )
            asyncio.create_task(handle_imagegen_api(text, "", ctx, game_data, agent))
            return text

    agent.before_llm_cb = before_llm
    agent.before_tts_cb = before_tts

    @agent.on("user_speech_committed")
    def on_user(msg: llm.ChatMessage):
        logger.info(f"User said: {msg.content}")
        logger.info("Chat context length after user message: %d", len(agent.chat_ctx.messages))

    @agent.on("agent_speech_committed")
    def on_agent(msg: llm.ChatMessage):
        logger.info(f"Agent said: {msg.content}")
        logger.info("Chat context length after agent message: %d", len(agent.chat_ctx.messages))

    ctx.add_shutdown_callback(lambda: logger.info("Session ended."))

    logger.info("Starting voice agent")
    agent.start(ctx.room)
    logger.info("Voice agent started")

    greeting = game_data.latest_summary.summary_text if game_data and game_data.latest_summary else (
        game_data.intro if game_data and game_data.intro else "Let's start!"
    )
    logger.info("Initial greeting: %s", greeting)
    await agent.say(greeting, allow_interruptions=True)

if __name__ == "__main__":
    cli.run_app(WorkerOptions(
        shutdown_process_timeout=5,
        entrypoint_fnc=entrypoint,
        prewarm_fnc=prewarm
    ))
