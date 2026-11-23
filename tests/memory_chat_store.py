"""Archivio delle chat in memoria per i test: stesso comportamento di PostgresChatStore."""

from copy import deepcopy
from datetime import UTC, datetime

from backend_service.store import (
    DEFAULT_TITLE,
    ChatStore,
    StoreUnavailable,
    clean_title,
    title_from,
)

_CHAT_KEYS = ("id", "titolo", "creata", "ultimo_messaggio")


class MemoryChatStore(ChatStore):
    def __init__(self):
        self.down = False
        self._chats: dict[int, dict] = {}
        self._messages: list[dict] = []  # ognuno con chat_id
        self._next_chat = 1
        self._next_message = 1

    def _check(self):
        if self.down:
            raise StoreUnavailable("Database non raggiungibile (finto).")

    @staticmethod
    def _chat_view(chat: dict) -> dict:
        return deepcopy({k: chat[k] for k in _CHAT_KEYS})

    @staticmethod
    def _message_view(message: dict) -> dict:
        return deepcopy({k: v for k, v in message.items() if k != "chat_id"})

    def create_chat(self, title=None):
        self._check()
        title = clean_title(title)
        chat = {
            "id": self._next_chat,
            "titolo": title,
            "creata": datetime.now(UTC),
            "ultimo_messaggio": None,
            "cronologia": [],
            "riassunto": "",
            "in_sospeso": None,
        }
        self._next_chat += 1
        self._chats[chat["id"]] = chat
        return self._chat_view(chat)

    def list_chats(self):
        self._check()
        chats = sorted(
            self._chats.values(),
            key=lambda c: (c["ultimo_messaggio"] or c["creata"], c["id"]),
            reverse=True,
        )
        return [self._chat_view(c) for c in chats]

    def get_chat(self, chat_id):
        self._check()
        chat = self._chats.get(chat_id)
        return None if chat is None else deepcopy(chat)

    def get_messages(self, chat_id):
        self._check()
        return [self._message_view(m) for m in self._messages if m["chat_id"] == chat_id]

    def delete_chat(self, chat_id):
        self._check()
        if self._chats.pop(chat_id, None) is None:
            return False
        self._messages = [m for m in self._messages if m["chat_id"] != chat_id]
        return True

    def set_pending(self, chat_id, pending):
        self._check()
        chat = self._chats.get(chat_id)
        if chat is None:
            return False
        chat["in_sospeso"] = deepcopy(pending)
        return True

    def save_turn(self, chat_id, question, answer, tools, lines, history, summary):
        self._check()
        chat = self._chats.get(chat_id)
        if chat is None:
            return None
        now = datetime.now(UTC)
        created = []
        for role, text, used, extra in (
            ("utente", question, [], []),
            ("assistente", answer, tools, lines),
        ):
            message = {
                "id": self._next_message,
                "chat_id": chat_id,
                "ruolo": role,
                "contenuto": text,
                "strumenti": deepcopy(used),
                "righe": deepcopy(extra),
                "creato": now,
            }
            self._next_message += 1
            self._messages.append(message)
            created.append(self._message_view(message))
        chat["cronologia"] = deepcopy(history)
        chat["riassunto"] = summary
        chat["in_sospeso"] = None
        chat["ultimo_messaggio"] = now
        if chat["titolo"] == DEFAULT_TITLE:
            chat["titolo"] = title_from(question)
        return created[0], created[1]

    def ping(self):
        self._check()
