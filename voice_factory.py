"""
Factory for creating voice components (STT/TTS) for different languages.
Each language has an optimally selected provider and voice.
"""

import logging
from livekit.plugins import openai, cartesia, deepgram, elevenlabs
from livekit.plugins.elevenlabs.tts import VoiceSettings

logger = logging.getLogger("voice-factory")


class VoiceComponentFactory:
    """Factory for creating STT and TTS components for different languages"""

    @staticmethod
    def create_tts(language: str, speed: float = 1.0):
        """
        Creates TTS component for specified language and speed

        Args:
            language: Language code (en, ru, nl, fr, es)
            speed: Speech speed (0.5, 0.75, 1.0, 1.5, 1.75)

        Returns:
            TTS component from corresponding provider
        """
        logger.info(f"Creating TTS for language: {language}, speed: {speed}")

        if language == "en":
            # return elevenlabs.TTS(
                # model="eleven_multilingual_v2",
                # voice_id="wXKeh4OrqzO6TjKQTRdw",  # Special EN voice
            #     voice_settings=VoiceSettings(
            #             stability=0.40,
            #             similarity_boost=0.50,
            #             style=0.0,
            #             use_speaker_boost=True
            #         )
            # )
            return openai.TTS(
                model="tts-1",
                voice="ash",  # Best voice for English
                speed=speed
            )

        elif language == "ru":
            return openai.TTS(
                model="tts-1",
                voice="nova",  # Good voice for Russian
                speed=speed
            )
            # return elevenlabs.TTS(
            #     model="eleven_multilingual_v2",
            #     voice_id="8JVbfL6oEdmuxKn5DK2C",  # Special RU voice
            #     # voice_settings=VoiceSettings(
            #     #         stability=0.40,
            #     #         similarity_boost=0.50,
            #     #         style=0.0,
            #     #         use_speaker_boost=True
            #     #     )
            #     )
        elif language == "nl":
            # return elevenlabs.TTS(
            #     voice="dutch_female_voice_id"  # Special Dutch voice
            # )
            return cartesia.TTS(
                language="nl",
                model="sonic-3.5",
                voice="9e8db62d-056f-47f3-b3b6-1b05767f9176"  # Cartesia voice for Dutch
            )

        elif language == "fr":
            return cartesia.TTS(
                language="fr",
                model="sonic-3.5",
                voice="5c3c89e5-535f-43ef-b14d-f8ffe148c1f0"  # ESP voice for French
            )
            # return openai.TTS(
            #     model="tts-1",
            #     voice="nova",  # Best for French
            #     speed=speed
            # )
        elif language == "es":
            return cartesia.TTS(
                language="es",
                model="sonic-3.5",
                voice="2695b6b5-5543-4be1-96d9-3967fb5e7fec"  # ESP voice for Spanish
            )
        else:
            # Fallback to English
            logger.warning(f"Unknown language {language}, falling back to English")
            return openai.TTS(
                model="tts-1",
                voice="ash",
                speed=speed
            )

    @staticmethod
    def create_stt(language: str):
        """
        Creates STT component for specified language

        Args:
            language: Language code (en, ru, nl, fr, es)

        Returns:
            STT component from corresponding provider
        """
        logger.info(f"Creating STT for language: {language}")

        if language == "en":
            return openai.STT(language="en")
        elif language == "ru":
            return deepgram.STT(language="ru")
        elif language == "nl":
            return openai.STT(language="nl")
        elif language == "fr":
            return deepgram.STT(language="fr")
        elif language == "es":
            return openai.STT(language="es")
        else:
            # Fallback to English
            logger.warning(f"Unknown language {language}, falling back to English")
            return openai.STT(language="en")

    @staticmethod
    def get_supported_languages():
        """Returns list of supported languages"""
        return ["en", "ru", "nl", "fr", "es"]

    @staticmethod
    def get_supported_speeds():
        """Returns list of supported speech speeds"""
        return [0.5, 0.75, 1.0, 1.5, 1.75]

    @staticmethod
    def validate_settings(language: str, speed: float) -> tuple[str, float]:
        """
        Validates and normalizes settings

        Args:
            language: Language code
            speed: Speech speed

        Returns:
            Tuple with valid (language, speed)
        """
        # Language validation
        if language not in VoiceComponentFactory.get_supported_languages():
            logger.warning(f"Invalid language {language}, using 'en'")
            language = "en"

        # Speed validation
        supported_speeds = VoiceComponentFactory.get_supported_speeds()
        if speed not in supported_speeds:
            # Find closest supported speed
            closest_speed = min(supported_speeds, key=lambda x: abs(x - speed))
            logger.warning(f"Invalid speed {speed}, using closest: {closest_speed}")
            speed = closest_speed

        return language, speed
