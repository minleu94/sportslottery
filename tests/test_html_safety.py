from ui.html_safety import html_text
from unittest.mock import MagicMock, patch


def test_html_text_escapes_markup_and_quotes():
    assert html_text('<img src=x onerror="alert(1)">') == "&lt;img src=x onerror=&quot;alert(1)&quot;&gt;"
    assert html_text(None) == ""


def test_line_binding_card_escapes_profile_name_and_never_renders_pin():
    from ui.profile_view import render_line_binding_card

    with patch("ui.profile_view.st.markdown") as markdown, patch("ui.profile_view.st.expander") as expander:
        expander.return_value.__enter__.return_value = MagicMock()
        render_line_binding_card(
            {"id": "player-1", "name": '<img src=x onerror="alert(1)">', "pin_code": "1234"}
        )

    rendered = "\n".join(str(call.args[0]) for call in markdown.call_args_list)
    assert "<img src=x" not in rendered
    assert "&lt;img src=x onerror=&quot;alert(1)&quot;&gt;" in rendered
    assert "1234" not in rendered
