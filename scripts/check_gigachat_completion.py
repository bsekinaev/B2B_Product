"""Ручной smoke-тест реального текстового ответа GigaChat без вывода секретов."""

from app.config import Settings
from app.llm.client import GigaChatProvider, LLMError


def main() -> int:
    provider = GigaChatProvider(Settings())
    try:
        text = provider.generate_text(
            system_prompt="Отвечай кратко на русском языке.",
            user_prompt="Напиши одно слово: проверено.",
        )
    except LLMError as error:
        print(f"GIGACHAT COMPLETION: FAIL ({error.code.value})")
        return 1

    print(f"GIGACHAT COMPLETION: PASS (characters={len(text)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
