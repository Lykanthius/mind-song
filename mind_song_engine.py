# mind_song_engine.py
# Canonical Mind Song engine (platform-agnostic).
#
# Phase 2.2 (1A-Lite, Path A):
# - This file will gradually absorb story logic + state.
# - Desktop terminal and Mobile/Web will be thin adapters on top of this engine.
#
# For now: scaffold only (no gameplay moved yet).

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

def _mk_output(
    lines: List[str],
    prompt: str = "> ",
    input_mode: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Standard engine output contract (v0).
    We keep it small now; we can extend later (choices, audio intents, etc.).
    """
    return {
        "lines": lines,
        "beats": None,  # ---> NEW (Phase 2.8): authoritative desktop print_pause() boundaries
        "prompt": prompt,
        "input_mode": input_mode,
        # Reserved for later (keep stable keys so adapters don't churn)
        "choices": None,
        "audio": {"bgm": None, "sfx": []},
        "meta": {},
    }

@dataclass
class MindSongEngine:
    """
    Canonical game engine.
    Holds all story state and produces display output.
    """
    lang: str = "en"  # future: "pt_br"
    state: Dict[str, Any] = field(default_factory=dict)
    _started: bool = False

    def start(self) -> Dict[str, Any]:
        """
        Begin a new session.
        Returns initial transcript lines.
        """
        self._started = True

        # Default to child path for the earliest mobile scaffold.
        # (We are NOT inventing content; we are only selecting which existing path to run.)
        self.state.setdefault("character", "child")
        self.state.setdefault("character_name", "")
        self.state.setdefault("player_role", "")
        self.state.setdefault("missing_parent", "")

        # Stage machine for Phase 2.2
        self.state["stage"] = "INTRO_NAME"

        character = self.state["character"]

        # Authored lines copied EXACTLY from mind_song.py:def intro()
        # IMPORTANT: Do not embed "\n" inside these strings; represent blank lines as "".
        lines = [
            f"Your {character} is still asleep in bed.",
            "They look like they're having a nightmare.",
            "You say their name softly to not startle them.",
            "What's their name?",
        ]

        out = _mk_output(lines, input_mode="TEXT")

        # ---> NEW (Phase 2.8): preserve desktop print_pause() boundaries exactly.
        # "What's their name?" is NOT a print_pause() beat; it belongs to the input prompt.
        out["beats"] = [
            [f"Your {character} is still asleep in bed."],
            ["They look like they're having a nightmare."],
            ["You say their name softly to not startle them."],
        ]

        out["meta"]["engine_ready"] = True
        return out

    def step(self, user_input: str) -> Dict[str, Any]:
        """
        Advance the game by one user input (one turn).
        Returns new transcript lines + prompt-as-lines.
        """
        if not self._started:
            return self.start()

        stage = self.state.get("stage", "INTRO_NAME")

        # IMPORTANT: do not invent narrative. Only route existing authored lines.
        raw = "" if user_input is None else str(user_input)
        s = raw.strip()

                # ---------------------------
        # Stage: name the character
        # ---------------------------
        if stage == "INTRO_NAME":
            # mind_song.py does not strip the name; it takes raw input.
            self.state["character_name"] = raw

            character = self.state.get("character", "child")
            character_name = self.state.get("character_name", "")

            # Authored lines copied EXACTLY from mind_song.py:def intro()
            # IMPORTANT: No embedded "\n" inside strings; use "" as blank lines.
            lines = [
                "",
                f"'{character_name}, it's just a bad dream.'",
                "They open their eyes and shout, 'It's gonna crash!'",
                "They look at you and say, 'You're the pilot, aren't you?!'",
                "You tell them you're here.",
            ]

            if character == "child":
                # Next: choose parent (valid_input behavior, no invention)
                self.state["stage"] = "CHOOSE_PARENT"

                # Authored choices from mind_song.py:def choose_parent()
                lines += [
                    "",
                    "1. Tell them, 'Mommy is here.'",
                    "2. Tell them, 'Daddy is here.'",
                ]

                out = _mk_output(lines, input_mode="MINIMAL")

                # ---> NEW (Phase 2.8): preserve the four desktop print_pause() beats exactly.
                out["beats"] = [
                    [f"'{character_name}, it's just a bad dream.'"],
                    ["They open their eyes and shout, 'It's gonna crash!'"],
                    ["They look at you and say, 'You're the pilot, aren't you?!'"],
                    ["You tell them you're here."],
                ]

                out["choices"] = [
                    {"key": "1", "line": "1. Tell them, 'Mommy is here.'"},
                    {"key": "2", "line": "2. Tell them, 'Daddy is here.'"},
                ]
                return out

        # ---------------------------
        # Stage: choose parent (valid_input)
        # ---------------------------
        if stage == "CHOOSE_PARENT":
            character = self.state.get("character", "child")
            character_name = self.state.get("character_name", "")
            player_role = self.state.get("player_role", "")
            player_name = self.state.get("player_name", "")

            # This mirrors mind_song.py:def valid_input()
            if s == "1" or s == "2":
                if s == "1":
                    self.state["player_role"] = "Mommy"
                    self.state["missing_parent"] = "Daddy"
                else:
                    self.state["player_role"] = "Daddy"
                    self.state["missing_parent"] = "Mommy"

                player_role = self.state["player_role"]

                # Authored lines copied EXACTLY from mind_song.py:def entry_point() (child branch)
                self.state["stage"] = "ENTRY_POINT_DONE"
                lines = [
                    "",
                    f"You sing to them, 'It's okay, {character_name}.'",
                    f"'{player_role} is here.'",
                ]
                return _mk_output(lines, input_mode="MINIMAL")

            # Invalid input branch: echo the player's invalid input (response).
            # IMPORTANT: do NOT print a prompt as a transcript line ("> ").
            # The prompt is returned via the structured `prompt` field and rendered by the UI.
            lines = [
                "",
                f"{character_name} replies, '{s}? I don't understand.'",
                "",
                "1. Tell them, 'Mommy is here.'",
                "2. Tell them, 'Daddy is here.'",
            ]

            out = _mk_output(lines, input_mode="MINIMAL")
            out["choices"] = [
                {"key": "1", "line": "1. Tell them, 'Mommy is here.'"},
                {"key": "2", "line": "2. Tell them, 'Daddy is here.'"},
            ]
            return out

        # For now, no invented continuation. (Next Phase will route into the next authored slice.)
        return _mk_output([])