import asyncio
from typing import AsyncIterable
from aiofile import async_open as open
from datetime import datetime
import aiohttp
import os
import dotenv

from livekit.agents import (
    Agent,
    AgentSession,
    JobContext,
    WorkerOptions,
    cli,
    llm,
    tts,
    vad,
)
from livekit.plugins import deepgram, openai, silero, cartesia, google
from livekit.plugins.turn_detector.multilingual import MultilingualModel
from dotenv import load_dotenv
import livekit.api

import logging
from uuid import UUID
from pydantic import BaseModel
from typing import Dict, Optional

load_dotenv()

logger = logging.getLogger("rpg-agent")
logger.setLevel(logging.INFO)
logging.getLogger("livekit").setLevel(logging.CRITICAL)

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

# async def send_to_imageGen_api(messages, turn_id, game_data: GameData):
#     async with aiohttp.ClientSession() as session:
#         payload = {
#             "pic_id": turn_id,
#             "chat_history": messages[-1],
#             "illustration_style": game_data.image_style_prompt,
#             "main_character": game_data.character_appearance
#         }
#         logger.info("Sending image generation payload: %s", payload)
#         async with session.post("https://storyimagegen-production.up.railway.app/process_chat",
#                                 timeout=60,
#                                 json=payload) as response:
#             return await response.json()

# async def save_next_turn_api(user_text: str, gm_text: str, game_id: str, image_url: str, image_prompt: str):
#     async with aiohttp.ClientSession() as session:
#         payload = {
#             "game_id": game_id,
#             "player_text": user_text,
#             "gm_response": gm_text,
#             "image_url": image_url,
#             "image_prompt": image_prompt
#         }
#         logger.info("Saving turn to API: %s", payload)
#         await session.post(f"{os.getenv('STORY_API_URL')}/turns", json=payload)


class Assistant(Agent):
    def __init__(self, game_data: GameData, ctx: JobContext, user_lang: str):
        super().__init__(
            instructions=f"""
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
        self.game_data = game_data
        self.ctx = ctx

    # async def handle_imagegen_api(self, gm_text, last_turn_id):
    #     try:
    #         chat_history = await self.get_chat_history()
    #         result = await send_to_imageGen_api(chat_history, last_turn_id, self.game_data)
    #         image_url = result.get('image_url')
    #         image_prompt = result.get('illustration_prompt')

    #         if image_url:
    #             self.ctx.proc.userdata["pic_url"] = image_url
    #             self.ctx.proc.userdata["image_prompt"] = image_prompt
    #             participant = await self.ctx.wait_for_participant()
    #             await self.ctx.room.local_participant.publish_data(image_url,
    #                                                            reliable=True,
    #                                                            destination_identities=[participant.identity],
    #                                                            topic="topic1")

    #             if len(chat_history) > 2:
    #                 user_text = chat_history[-1].content
    #                 await save_next_turn_api(user_text, gm_text, str(self.game_data.game.id), image_url, image_prompt)
    #     except Exception as e:
    #         logger.error(f"ImageGen API error: {e}")


async def entrypoint(ctx: JobContext):
    await ctx.connect()

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

    assistant = Assistant(game_data, ctx, user_lang)

    session = AgentSession(
        stt=deepgram.STT(language=user_lang_code),
        llm=openai.LLM(model="gpt-4.1-nano"),
        tts=cartesia.TTS(
            speed=0.5 if user_lang_code == "ru" else (0.8 if user_lang_code == "nl" else 1),
            voice="da05e96d-ca10-4220-9042-d8acef654fa9" if user_lang_code == "ru" else (
                "9e8db62d-056f-47f3-b3b6-1b05767f9176" if user_lang_code == "nl" else "da05e96d-ca10-4220-9042-d8acef654fa9"
            ),
            language=user_lang_code
        ),
        vad=silero.VAD.load(),
        turn_detection=MultilingualModel(),
    )

    @session.on("user_state_changed")
    def on_user_state_changed(ev):
        logger.info(f"User state changed: {ev.old_state} -> {ev.new_state}")

    @session.on("agent_state_changed")
    def on_agent_state_changed(ev):
        logger.info(f"Agent state changed: {ev.old_state} -> {ev.new_state}")

    @session.on("participant_connected")
    def on_participant_connected(participant):
        logger.info(f"Participant connected: {participant.identity}")

    @session.on("track_subscribed")
    def on_track_subscribed(track, publication, participant):
        logger.info(f"Track subscribed: {track.sid} from participant {participant.identity}")

    ctx.add_shutdown_callback(lambda: logger.info("Session ended."))

    logger.info("Starting agent session")
    await session.start(
        room=ctx.room,
        agent=assistant,
    )
    logger.info("Agent session started")

    greeting = game_data.latest_summary.summary_text if game_data and game_data.latest_summary else (
        game_data.intro if game_data and game_data.intro else "Let's start!"
    )
    await session.generate_reply(instructions=greeting)


if __name__ == "__main__":
    cli.run_app(WorkerOptions(
        shutdown_process_timeout=5,
        entrypoint_fnc=entrypoint,
    ))
