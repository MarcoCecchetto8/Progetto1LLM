import pytest

from notes_service.store import NoteStore


@pytest.fixture
def store(tmp_path):
    return NoteStore(tmp_path / "sub" / "notes.db")


def test_add_returns_note_and_creates_folder(tmp_path):
    store = NoteStore(tmp_path / "sub" / "notes.db")
    note = store.add("  consegnare il report ", "2026-11-13")
    assert note["id"] == 1
    assert note["text"] == "consegnare il report"
    assert note["due_date"] == "2026-11-13"
    assert note["created_at"].endswith("+00:00")
    assert (tmp_path / "sub").is_dir()


def test_due_date_normalization(store):
    assert store.add("x", "")["due_date"] is None
    assert store.add("x", None)["due_date"] is None
    assert store.add("x", " 2026-11-13 ")["due_date"] == "2026-11-13"


def test_special_characters_are_stored_verbatim(store):
    texts = ['l\'esame "finale" 🎓\nseconda riga', "'); DROP TABLE notes;--"]
    for text in texts:
        note = store.add(text)
        assert store.get(note["id"]) == note
        assert note["text"] == text
    assert store.list_notes()[0] == 2


def test_text_errors(store):
    with pytest.raises(ValueError, match="vuoto"):
        store.add("   ")
    with pytest.raises(ValueError, match=r"massimo 500 caratteri \(ricevuti 501\)"):
        store.add("a" * 501)
    assert len(store.add("a" * 500)["text"]) == 500


def test_due_date_errors(store):
    with pytest.raises(ValueError) as exc:
        store.add("x", "venerdì")
    assert 'Scadenza "venerdì" non valida: formato atteso AAAA-MM-GG' in str(exc.value)
    with pytest.raises(ValueError, match="inesistente"):
        store.add("x", "2026-02-30")
    assert store.add("x", "2020-01-01")["due_date"] == "2020-01-01"


def test_ordering(store):
    for due in ["2026-12-01", None, "2026-11-01", None, "2026-11-20"]:
        store.add("n", due)
    assert [n["id"] for n in store.list_notes()[1]] == [3, 5, 1, 4, 2]


def test_limit(store):
    for _ in range(5):
        store.add("n")
    total, notes = store.list_notes(2)
    assert total == 5 and len(notes) == 2
    for bad in (0, 51):
        with pytest.raises(ValueError, match="fra 1 e 50"):
            store.list_notes(bad)


def test_get_and_delete(store):
    first = store.add("uno")
    assert store.get(99) is None
    assert store.delete(1) == first
    assert store.get(1) is None
    assert store.delete(1) is None


def test_persistence(tmp_path):
    path = tmp_path / "notes.db"
    note = NoteStore(path).add("resta", "2026-11-13")
    assert NoteStore(path).list_notes() == (1, [note])
