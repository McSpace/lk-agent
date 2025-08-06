"""
Фабрика для создания голосовых компонентов (STT/TTS) для разных языков.
Каждый язык имеет оптимально подобранный провайдер и голос.
"""

import logging
from livekit.plugins import openai, cartesia, deepgram, elevenlabs
from livekit.plugins.elevenlabs.tts import VoiceSettings

logger = logging.getLogger("voice-factory")


class VoiceComponentFactory:
    """Фабрика для создания STT и TTS компонентов для разных языков"""
    
    @staticmethod
    def create_tts(language: str, speed: float = 1.0):
        """
        Создает TTS компонент для указанного языка и скорости
        
        Args:
            language: Код языка (en, ru, nl, fr, es)
            speed: Скорость речи (0.5, 0.75, 1.0, 1.5, 1.75)
            
        Returns:
            TTS компонент соответствующего провайдера
        """
        logger.info(f"Creating TTS for language: {language}, speed: {speed}")
        
        if language == "en":
            return elevenlabs.TTS(
                model="eleven_multilingual_v2",
                voice_id="wXKeh4OrqzO6TjKQTRdw",  # Специальный EN голос
            #     voice_settings=VoiceSettings(
            #             stability=0.40,
            #             similarity_boost=0.50,
            #             style=0.0,
            #             use_speaker_boost=True
            #         )
            )  
            # return openai.TTS(
            #     model="tts-1",
            #     voice="ash",  # Лучший голос для английского
            #     speed=speed
            # )
            
        elif language == "ru":
            return cartesia.TTS(
                language="ru",
                model="sonic-2",
                voice="da05e96d-ca10-4220-9042-d8acef654fa9"  # Русский голос Cartesia
            )
            # return elevenlabs.TTS(
            #     model="eleven_multilingual_v2",
            #     voice_id="8JVbfL6oEdmuxKn5DK2C",  # Специальный RU голос
            #     # voice_settings=VoiceSettings(
            #     #         stability=0.40,
            #     #         similarity_boost=0.50,
            #     #         style=0.0,
            #     #         use_speaker_boost=True
            #     #     )
            #     )          
        elif language == "nl":
            # return elevenlabs.TTS(
            #     voice="dutch_female_voice_id"  # Специальный голландский голос
            # )
            return cartesia.TTS(
                language="nl",
                model="sonic-2",
                voice="9e8db62d-056f-47f3-b3b6-1b05767f9176"  # Голос Cartesia для голландского
            )

        elif language == "fr":
            return cartesia.TTS(
                language="fr",
                model="sonic-2",
                voice="5c3c89e5-535f-43ef-b14d-f8ffe148c1f0"  # Голос ESP для французского
            )            
            # return openai.TTS(
            #     model="tts-1",
            #     voice="nova",  # Лучший для французского
            #     speed=speed
            # )
        elif language == "es":
            return cartesia.TTS(
                language="es",
                model="sonic-2",
                voice="2695b6b5-5543-4be1-96d9-3967fb5e7fec"  # Голос ESP для голландского
            )            
        else:
            # Fallback на английский
            logger.warning(f"Unknown language {language}, falling back to English")
            return openai.TTS(
                model="tts-1", 
                voice="ash", 
                speed=speed
            )
    
    @staticmethod
    def create_stt(language: str):
        """
        Создает STT компонент для указанного языка
        
        Args:
            language: Код языка (en, ru, nl, fr, es)
            
        Returns:
            STT компонент соответствующего провайдера
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
            # Fallback на английский
            logger.warning(f"Unknown language {language}, falling back to English")
            return openai.STT(language="en")
    
    @staticmethod
    def get_supported_languages():
        """Возвращает список поддерживаемых языков"""
        return ["en", "ru", "nl", "fr", "es"]
    
    @staticmethod
    def get_supported_speeds():
        """Возвращает список поддерживаемых скоростей речи"""
        return [0.5, 0.75, 1.0, 1.5, 1.75]
    
    @staticmethod
    def validate_settings(language: str, speed: float) -> tuple[str, float]:
        """
        Валидирует и нормализует настройки
        
        Args:
            language: Код языка
            speed: Скорость речи
            
        Returns:
            Tuple с валидными (language, speed)
        """
        # Валидация языка
        if language not in VoiceComponentFactory.get_supported_languages():
            logger.warning(f"Invalid language {language}, using 'en'")
            language = "en"
        
        # Валидация скорости
        supported_speeds = VoiceComponentFactory.get_supported_speeds()
        if speed not in supported_speeds:
            # Находим ближайшую поддерживаемую скорость
            closest_speed = min(supported_speeds, key=lambda x: abs(x - speed))
            logger.warning(f"Invalid speed {speed}, using closest: {closest_speed}")
            speed = closest_speed
        
        return language, speed