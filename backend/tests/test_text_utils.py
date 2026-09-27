from app.export import to_srt, to_txt, to_vtt
from app.glossary import Glossary
from app.schemas import CaptionEvent
from app.validation import is_valid_lang, is_valid_session_id, is_valid_source_lang


def _event(text, start, end):
    return CaptionEvent(session_id="s", lang="es", text=text, is_final=True, start_s=start, end_s=end)


def test_srt_and_vtt_formatting():
    events = [_event("Hola", 0.0, 4.25), _event("Chau", 3661.5, 3662.0)]
    assert to_srt(events) == (
        "1\n00:00:00,000 --> 00:00:04,250\nHola\n\n"
        "2\n01:01:01,500 --> 01:01:02,000\nChau\n"
    )
    assert to_vtt(events).startswith("WEBVTT\n\n00:00:00.000 --> 00:00:04.250\nHola\n")
    assert to_txt(events) == "Hola\nChau"


def test_glossary_parsing_and_corrections():
    glossary = Glossary.parse(
        "# comentario\n\nNerdearla\nKapsch Henning => captioning\ncapshening => captioning\n"
    )
    assert glossary.keep == ["Nerdearla"]
    assert glossary.corrections == [("Kapsch Henning", "captioning"), ("capshening", "captioning")]
    assert glossary.apply_corrections("Live kapsch henning and Capshening!") == "Live captioning and captioning!"
    # Solo palabras completas.
    assert glossary.apply_corrections("capsheningX") == "capsheningX"
    assert glossary.hotwords() == "Nerdearla captioning"
    assert '"Nerdearla" se mantiene tal cual' in glossary.prompt_instructions()


def test_empty_glossary():
    glossary = Glossary.parse("# nada\n")
    assert glossary.prompt_instructions() == ""
    assert glossary.hotwords() is None


def test_session_id_validation():
    for ok in ["escenario-1", "sala_2", "a", "x" * 64]:
        assert is_valid_session_id(ok)
    for bad in ["", "Sala", "-x", "a b", "a/b", 'a"b', "x" * 65, "ñ"]:
        assert not is_valid_session_id(bad)


def test_language_validation():
    assert is_valid_lang("es") and is_valid_lang("pt-br")
    assert not is_valid_lang("auto") and not is_valid_lang("../es") and not is_valid_lang("ES")
    assert is_valid_source_lang("auto")
