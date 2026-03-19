"""Tests for tmb.nodes.discussion — _is_ready_to_build and _read_owner_answer."""

import pytest

from tmb.nodes.discussion import _is_ready_to_build, _read_owner_answer, _ANSWER_MARKER


class TestIsReadyToBuild:
    """Tests for the _is_ready_to_build() function."""

    def test_exact_signal_uppercase(self):
        assert _is_ready_to_build("TRUST ME BRO, LET'S BUILD") is True

    def test_exact_signal_mixed_case(self):
        assert _is_ready_to_build("Trust Me Bro, Let's Build") is True

    def test_exact_signal_embedded_in_message(self):
        assert _is_ready_to_build("I've analyzed everything. TRUST ME BRO, LET'S BUILD") is True

    def test_partial_signal_trust_me_bro(self):
        assert _is_ready_to_build("Trust me bro, I've got this") is True

    def test_ready_to_build_the_blueprint(self):
        assert _is_ready_to_build("Ready to build the blueprint") is True

    def test_ready_to_create_plan(self):
        assert _is_ready_to_build("I'm ready to create the plan") is True

    def test_going_to_write_blueprint(self):
        assert _is_ready_to_build("I'm going to write the blueprint now") is True

    def test_lets_build_this_thing(self):
        assert _is_ready_to_build("Let's build this thing") is True

    def test_lets_building(self):
        assert _is_ready_to_build("Let's get building") is True

    def test_shall_i_proceed_to_build(self):
        assert _is_ready_to_build("Shall I proceed to build?") is True

    def test_shall_we_go_ahead(self):
        assert _is_ready_to_build("Shall we go ahead?") is True

    def test_hand_off_to_executor(self):
        assert _is_ready_to_build("I'll hand this off to the executor") is True

    def test_hand_to_executor(self):
        assert _is_ready_to_build("Ready to hand this to the executor") is True

    def test_want_me_to_kick_it_off(self):
        assert _is_ready_to_build("Want me to kick it off?") is True

    def test_kick_this_off(self):
        assert _is_ready_to_build("Let me kick this off") is True

    def test_fully_aligned(self):
        assert _is_ready_to_build("I'm fully aligned on the requirements") is True

    def test_have_the_full_picture(self):
        assert _is_ready_to_build("I have the full picture") is True

    def test_ive_got_the_full_picture(self):
        assert _is_ready_to_build("I've got the full picture now") is True

    def test_proceed_to_blueprint(self):
        assert _is_ready_to_build("Let's proceed to the blueprint") is True

    def test_proceed_with_build(self):
        assert _is_ready_to_build("I'll proceed with the build") is True

    # False positive guards
    def test_i_have_some_questions(self):
        assert _is_ready_to_build("I have some questions") is False

    def test_heres_what_i_found(self):
        assert _is_ready_to_build("Here's what I found so far") is False

    def test_let_me_check_the_codebase(self):
        assert _is_ready_to_build("Let me check the codebase") is False

    def test_empty_string(self):
        assert _is_ready_to_build("") is False

    def test_unrelated_statement(self):
        assert _is_ready_to_build("I see some risks in this approach") is False

    def test_partial_match_does_not_trigger(self):
        # "build" alone without readiness context should not match
        assert _is_ready_to_build("What should we build?") is False

    def test_want_me_to_proceed(self):
        assert _is_ready_to_build("Want me to proceed with this?") is True


class TestReadOwnerAnswer:
    """Tests for the _read_owner_answer() function."""

    def test_normal_answer(self, tmp_path):
        f = tmp_path / "DISCUSSION.md"
        f.write_text(f"Some content\n\n{_ANSWER_MARKER}\n\nYes, use option A.\n")
        assert _read_owner_answer(f) == "Yes, use option A."

    def test_no_marker_in_file(self, tmp_path):
        f = tmp_path / "DISCUSSION.md"
        f.write_text("Some content without any marker\n")
        assert _read_owner_answer(f) == ""

    def test_file_does_not_exist(self, tmp_path):
        f = tmp_path / "DISCUSSION.md"
        assert _read_owner_answer(f) == ""

    def test_displaced_instructions_stripped(self, tmp_path):
        f = tmp_path / "DISCUSSION.md"
        content = (
            f"Some header content\n\n"
            f"{_ANSWER_MARKER}\n\n"
            f"## Your Answer\n\n"
            f"> Write your answers below the `{_ANSWER_MARKER}` line.\n"
            f"> Do not edit anything above it. Save the file when done.\n\n"
            f"My actual answer here.\n"
        )
        f.write_text(content)
        result = _read_owner_answer(f)
        assert result == "My actual answer here."
        assert "## Your Answer" not in result
        assert "Write your answers" not in result
        assert "Do not edit" not in result
        assert "Save the file" not in result

    def test_only_instructions_no_real_answer(self, tmp_path):
        f = tmp_path / "DISCUSSION.md"
        content = (
            f"Some header\n\n"
            f"{_ANSWER_MARKER}\n\n"
            f"## Your Answer\n\n"
            f"> Write your answers below the `{_ANSWER_MARKER}` line.\n"
            f"> Do not edit anything above it. Save the file when done.\n"
        )
        f.write_text(content)
        assert _read_owner_answer(f) == ""

    def test_empty_content_below_marker(self, tmp_path):
        f = tmp_path / "DISCUSSION.md"
        f.write_text(f"Some content\n\n{_ANSWER_MARKER}\n\n   \n")
        assert _read_owner_answer(f) == ""

    def test_marker_at_end_of_file(self, tmp_path):
        f = tmp_path / "DISCUSSION.md"
        f.write_text(f"Some content\n\n{_ANSWER_MARKER}")
        assert _read_owner_answer(f) == ""

    def test_multiline_answer_preserved(self, tmp_path):
        f = tmp_path / "DISCUSSION.md"
        content = (
            f"Some header\n\n"
            f"{_ANSWER_MARKER}\n\n"
            f"1. Use option A\n"
            f"2. Skip the caching layer\n"
            f"3. Deploy on Fridays is fine\n"
        )
        f.write_text(content)
        result = _read_owner_answer(f)
        assert "1. Use option A" in result
        assert "2. Skip the caching layer" in result
        assert "3. Deploy on Fridays is fine" in result

    def test_non_instruction_blockquotes_preserved(self, tmp_path):
        """Blockquotes that aren't instructions should be kept."""
        f = tmp_path / "DISCUSSION.md"
        content = (
            f"Some header\n\n"
            f"{_ANSWER_MARKER}\n\n"
            f"> This is a user quote I want to reference\n"
            f"My answer here.\n"
        )
        f.write_text(content)
        result = _read_owner_answer(f)
        assert "> This is a user quote I want to reference" in result
        assert "My answer here." in result
