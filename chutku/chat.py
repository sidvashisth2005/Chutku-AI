from __future__ import annotations

from chutku.presentation import present
from chutku.planning import execute_request
from chutku.runtime import Runtime


HELP_TEXT = (
    "Try: what time is it | system status | list files | read file PATH | "
    "create folder NAME | write TEXT to PATH | undo last write | list windows | capabilities | "
    "remember KEY = VALUE | recall WORD | memories | forget KEY | open notepad | "
    "open calculator | focus notepad | check calculator | list voices | say TEXT | speech recognition status | listen for a command. Type exit to leave."
)


def reply(message: str, runtime: Runtime) -> str:
    """Return a safe conversational response for one deterministic request."""
    normalized = message.strip()
    if not normalized:
        return "Please enter a request, or type help."
    if normalized.casefold() == "help":
        return HELP_TEXT
    return present(execute_request(normalized, runtime))


def run_chat(runtime: Runtime) -> None:
    print("Chutku text console is ready. This is local, deterministic, and limited to the sandbox.")
    print(HELP_TEXT)
    while True:
        try:
            message = input("You: ")
        except (EOFError, KeyboardInterrupt):
            print("\nChutku: Goodbye.")
            return
        if message.strip().casefold() in {"exit", "quit"}:
            print("Chutku: Goodbye.")
            return
        print(f"Chutku: {reply(message, runtime)}")
