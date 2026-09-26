# mind_song_engine.py
# Canonical Mind Song engine (platform-agnostic).
#
# Phase 2.2 (1A-Lite, Path A):
# - This file will gradually absorb story logic + state.
# - Desktop terminal and Mobile/Web will be thin adapters on top of this engine.
#
# For now: scaffold only (no gameplay moved yet).

from __future__ import annotations

import random  # ---> NEW (Phase 2.8): canonical gameplay randomness moves into the engine

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# ---> NEW (Phase 2.8): canonical timed-choice durations from mind_song.py
TIMER_SECONDS_FINAL = 10
TIMER_SECONDS_TEST = 5

# Use TEST during development; switch to FINAL for production pacing.
TIMER_SECONDS = TIMER_SECONDS_TEST

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

    # ---> NEW (Phase 2.8): engine-owned equivalent of mind_song.py:def get_lives()
    def get_lives(self) -> int:
        lives = random.choice([2, 3])
        self.state["lives"] = lives
        return lives

    # ---> NEW (Phase 2.8.C.29): engine-owned child timeout idle-response bag.
    # Mirrors desktop get_idle_character_response(): shuffle all four,
    # then pop without repeats until the bag is empty.
    def get_child_idle_response(self) -> str:
        bag = self.state.get("child_idle_bag")

        if not bag:
            bag = [
                "Are you paying attention to me?",
                "I'm hungry.",
                "Can I have a puppy?",
                "Can I play on the computer?",
            ]
            random.shuffle(bag)
            self.state["child_idle_bag"] = bag

        return self.state["child_idle_bag"].pop()
    
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
                self.state["stage"] = "CHILD_LEVEL_ONE_START"
                lines = [
                    "",
                    f"You sing to them, 'It's okay, {character_name}.'",
                    f"'{player_role} is here.'",
                    "",
                    f"{character_name} squints at you and looks at the bracelet hanging above the bed. Maybe one of you will wear it today.",
                    "",
                    f"{character_name} says they don't want to spend the night with you anymore because of the nightmares.",
                ]

                out = _mk_output(lines, input_mode="MINIMAL")

                # ---> NEW (Phase 2.8): preserve desktop print_pause() boundaries through the first child Level 1 beat.
                out["beats"] = [
                    [f"You sing to them, 'It's okay, {character_name}.'"],
                    [f"'{player_role} is here.'"],
                    [f"{character_name} squints at you and looks at the bracelet hanging above the bed. Maybe one of you will wear it today."],
                    [f"{character_name} says they don't want to spend the night with you anymore because of the nightmares."],
                ]

                # ---> NEW (Phase 2.8): engine declares the canonical allowance
                # for the upcoming timed moral-choice turn.
                out["meta"]["choice_timeout_seconds"] = TIMER_SECONDS

                # ---> NEW (Phase 2.8): desktop child_level_one() calls get_lives()
                # immediately after its opening print_pause() beat.
                self.get_lives()

                # ---> NEW (Phase 2.8): persist the authored child Level 1 bad-choice sequence
                # across separate mobile engine turns.
                self.state["child_level_one_bad_choices"] = [
                    "Tell them that nightmares are not real.",
                    "Tell them they need to go back to sleeping with diapers.",
                    "Tell them all the reasons why they're wrong."
                ]

                # ---> NEW (Phase 2.8): persist the authored child Level 1 escalation sequence
                # across separate mobile engine turns.
                self.state["child_level_one_character_escalates"] = [
                    f"{character_name} says, 'If bad dreams aren't real, why did the monsters pee in our bed?'",
                    f"{character_name} says it's your fault that {self.state['missing_parent']} died on the plane."
                ]

                # ---> NEW (Phase 2.8): desktop child_level_one() starts its bad-choice loop at index 0.
                # Engine state must persist this value across separate mobile input turns.
                self.state["child_level_one_index"] = 0

                # ---> NEW (Phase 2.8): emit the first authored timed moral-choice pair.
                # Desktop print_choice_pair() inserts a blank line before the choices,
                # then gives each choice line its own print_pause() beat.
                first_bad_choice = self.state["child_level_one_bad_choices"][0]

                out["lines"] += [
                    "",
                    "1. Put on the bracelet",
                    f"2. {first_bad_choice}",
                ]

                out["beats"] += [
                    ["1. Put on the bracelet"],
                    [f"2. {first_bad_choice}"],
                ]

                out["choices"] = [
                    {"key": "1", "line": "1. Put on the bracelet"},
                    {"key": "2", "line": f"2. {first_bad_choice}"},
                ]

                # ---> NEW (Phase 2.8): the next engine turn belongs to the
                # persistent equivalent of child_level_one()'s choice loop.
                self.state["stage"] = "CHILD_LEVEL_ONE_CHOICE"

                return out

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

            # ---> NEW (Phase 2.8): preserve the desktop invalid-response print_pause() beat exactly.
            out["beats"] = [
                [f"{character_name} replies, '{s}? I don't understand.'"],
            ]

            out["choices"] = [
                {"key": "1", "line": "1. Tell them, 'Mommy is here.'"},
                {"key": "2", "line": "2. Tell them, 'Daddy is here.'"},
            ]
            return out

        # ---------------------------
        # Stage: child Level 1 timed moral choice
        # ---------------------------
        if stage == "CHILD_LEVEL_ONE_CHOICE":
            character_name = self.state.get("character_name", "")
            missing_parent = self.state.get("missing_parent", "")

            # ---> NEW (Phase 2.8.C.30R): first timed-choice timeout resolves
            # completely in one engine step, matching desktop fall-through behavior.
            if (
                s == "__TIMEOUT__"
                and self.state.get("child_level_one_index", 0) == 0
            ):
                idle_response = self.get_child_idle_response()

                lives = self.state.get("lives", 0)
                index = self.state.get("child_level_one_index", 0)
                bad_choices = self.state["child_level_one_bad_choices"]
                character_escalates = self.state["child_level_one_character_escalates"]

                lives -= 1
                self.state["lives"] = lives

                escalation = character_escalates[index]

                index += 1
                self.state["child_level_one_index"] = index

                next_bad_choice = bad_choices[index]

                lines = [
                    "",
                    "(Indecision is a decision)",
                    "",
                    f"{character_name} says, '{idle_response}'",
                    "",
                    escalation,
                    "",
                    "1. Put on the bracelet",
                    f"2. {next_bad_choice}",
                ]

                out = _mk_output(lines, input_mode="MINIMAL")

                out["beats"] = [
                    ["(Indecision is a decision)"],
                    [f"{character_name} says, '{idle_response}'"],
                    [escalation],
                    ["1. Put on the bracelet"],
                    [f"2. {next_bad_choice}"],
                ]

                out["choices"] = [
                    {"key": "1", "line": "1. Put on the bracelet"},
                    {"key": "2", "line": f"2. {next_bad_choice}"},
                ]

                # Desktop timeout pressure sound is a semantic adapter intent.
                out["audio"]["sfx"] = ["timer_zero"]

                # The newly presented moral choice receives a fresh
                # canonical timed-choice allowance.
                out["meta"]["choice_timeout_seconds"] = TIMER_SECONDS

                return out

            # ---> NEW (Phase 2.8.C.31): second timed-choice timeout,
            # surviving branch. Two remaining lives fall to one.
            if (
                s == "__TIMEOUT__"
                and self.state.get("child_level_one_index", 0) == 1
                and self.state.get("lives", 0) > 1
            ):
                idle_response = self.get_child_idle_response()

                lives = self.state.get("lives", 0)
                index = self.state.get("child_level_one_index", 0)
                bad_choices = self.state["child_level_one_bad_choices"]
                character_escalates = self.state["child_level_one_character_escalates"]

                lives -= 1
                self.state["lives"] = lives

                escalation = character_escalates[index]

                index += 1
                self.state["child_level_one_index"] = index

                next_bad_choice = bad_choices[index]

                lines = [
                    "",
                    "(Indecision is a decision)",
                    "",
                    f"{character_name} says, '{idle_response}'",
                    "",
                    escalation,
                    "",
                    "1. Put on the bracelet",
                    f"2. {next_bad_choice}",
                ]

                out = _mk_output(lines, input_mode="MINIMAL")

                out["beats"] = [
                    ["(Indecision is a decision)"],
                    [f"{character_name} says, '{idle_response}'"],
                    [escalation],
                    ["1. Put on the bracelet"],
                    [f"2. {next_bad_choice}"],
                ]

                out["choices"] = [
                    {"key": "1", "line": "1. Put on the bracelet"},
                    {"key": "2", "line": f"2. {next_bad_choice}"},
                ]

                out["audio"]["sfx"] = ["timer_zero"]
                out["meta"]["choice_timeout_seconds"] = TIMER_SECONDS

                return out

            # ---> NEW (Phase 2.8.C.32): second timed-choice timeout,
            # zero-lives branch. Desktop still emits the second escalation
            # before the game-over scream.
            if (
                s == "__TIMEOUT__"
                and self.state.get("child_level_one_index", 0) == 1
                and self.state.get("lives", 0) == 1
            ):
                idle_response = self.get_child_idle_response()

                index = self.state.get("child_level_one_index", 0)
                character_escalates = self.state["child_level_one_character_escalates"]

                self.state["lives"] = 0

                escalation = character_escalates[index]

                index += 1
                self.state["child_level_one_index"] = index

                self.state["game_state"] = "game over"
                self.state["game_over_level"] = self.state.get("level", "one")
                self.state["stage"] = "CHILD_LEVEL_ONE_GAME_OVER"

                lines = [
                    "",
                    "(Indecision is a decision)",
                    "",
                    f"{character_name} says, '{idle_response}'",
                    "",
                    escalation,
                    "",
                    f"{character_name} screams, 'I don't want to be adopted by you anymore!'",
                    "",
                ]

                out = _mk_output(lines, prompt="", input_mode="MINIMAL")

                out["beats"] = [
                    ["(Indecision is a decision)"],
                    [f"{character_name} says, '{idle_response}'"],
                    [escalation],
                    [f"{character_name} screams, 'I don't want to be adopted by you anymore!'"],
                ]

                out["audio"]["sfx"] = ["timer_zero"]
                out["audio"]["bgm"] = "lose"

                return out

            # ---> NEW (Phase 2.8.C.33): third timed-choice timeout
            # exhausts the final life. Desktop has no third escalation.
            if (
                s == "__TIMEOUT__"
                and self.state.get("child_level_one_index", 0) == 2
                and self.state.get("lives", 0) == 1
            ):
                idle_response = self.get_child_idle_response()

                self.state["lives"] = 0
                self.state["child_level_one_index"] = 3

                self.state["game_state"] = "game over"
                self.state["game_over_level"] = self.state.get("level", "one")
                self.state["stage"] = "CHILD_LEVEL_ONE_GAME_OVER"

                lines = [
                    "",
                    "(Indecision is a decision)",
                    "",
                    f"{character_name} says, '{idle_response}'",
                    "",
                    f"{character_name} screams, 'I don't want to be adopted by you anymore!'",
                    "",
                ]

                out = _mk_output(lines, prompt="", input_mode="MINIMAL")

                out["beats"] = [
                    ["(Indecision is a decision)"],
                    [f"{character_name} says, '{idle_response}'"],
                    [f"{character_name} screams, 'I don't want to be adopted by you anymore!'"],
                ]

                out["audio"]["sfx"] = ["timer_zero"]
                out["audio"]["bgm"] = "lose"

                return out

            # ---> NEW (Phase 2.8): desktop child_level_one() good-choice branch.
            if s == "1":
                lines = [
                    "",
                    "Your pulse softens at the touch of the cool metal on your wrist.",
                    "",
                    "1. Ask them what they would do if their toy had a nightmare.",
                    f"2. Ask them what {missing_parent} would do if they had a nightmare.",
                ]

                out = _mk_output(lines, input_mode="MINIMAL")

                # Desktop gives the pulse line one print_pause() beat,
                # then print_choice_pair() gives each follow-up choice its own beat.
                out["beats"] = [
                    ["Your pulse softens at the touch of the cool metal on your wrist."],
                    ["1. Ask them what they would do if their toy had a nightmare."],
                    [f"2. Ask them what {missing_parent} would do if they had a nightmare."],
                ]

                out["choices"] = [
                    {
                        "key": "1",
                        "line": "1. Ask them what they would do if their toy had a nightmare.",
                    },
                    {
                        "key": "2",
                        "line": f"2. Ask them what {missing_parent} would do if they had a nightmare.",
                    },
                ]

                self.state["stage"] = "CHILD_LEVEL_ONE_FOLLOWUP"
                return out

            # ---> NEW (Phase 2.8): first desktop bad-choice cycle.
            # Initial lives are always 2 or 3, so the first bad choice
            # cannot reach game over.
            if s == "2" and self.state.get("child_level_one_index", 0) == 0:
                lives = self.state.get("lives", 0)
                index = self.state.get("child_level_one_index", 0)
                bad_choices = self.state["child_level_one_bad_choices"]
                character_escalates = self.state["child_level_one_character_escalates"]

                lives -= 1
                self.state["lives"] = lives

                escalation = character_escalates[index]

                index += 1
                self.state["child_level_one_index"] = index

                next_bad_choice = bad_choices[index]

                lines = [
                    "",
                    escalation,
                    "",
                    "1. Put on the bracelet",
                    f"2. {next_bad_choice}",
                ]

                out = _mk_output(lines, input_mode="MINIMAL")

                # Desktop prints the escalation as one print_pause() beat,
                # then each choice line as its own print_pause() beat.
                out["beats"] = [
                    [escalation],
                    ["1. Put on the bracelet"],
                    [f"2. {next_bad_choice}"],
                ]

                out["choices"] = [
                    {"key": "1", "line": "1. Put on the bracelet"},
                    {"key": "2", "line": f"2. {next_bad_choice}"},
                ]

                # The newly presented moral choice receives a fresh
                # canonical timed-choice allowance.
                out["meta"]["choice_timeout_seconds"] = TIMER_SECONDS

                return out

            # ---> NEW (Phase 2.8): second desktop bad-choice cycle,
            # surviving branch only. If 2 lives remain before this choice,
            # the player falls to 1 and reaches the third timed choice.
            if (
                s == "2"
                and self.state.get("child_level_one_index", 0) == 1
                and self.state.get("lives", 0) > 1
            ):
                lives = self.state.get("lives", 0)
                index = self.state.get("child_level_one_index", 0)
                bad_choices = self.state["child_level_one_bad_choices"]
                character_escalates = self.state["child_level_one_character_escalates"]

                lives -= 1
                self.state["lives"] = lives

                escalation = character_escalates[index]

                index += 1
                self.state["child_level_one_index"] = index

                next_bad_choice = bad_choices[index]

                lines = [
                    "",
                    escalation,
                    "",
                    "1. Put on the bracelet",
                    f"2. {next_bad_choice}",
                ]

                out = _mk_output(lines, input_mode="MINIMAL")

                out["beats"] = [
                    [escalation],
                    ["1. Put on the bracelet"],
                    [f"2. {next_bad_choice}"],
                ]

                out["choices"] = [
                    {"key": "1", "line": "1. Put on the bracelet"},
                    {"key": "2", "line": f"2. {next_bad_choice}"},
                ]

                out["meta"]["choice_timeout_seconds"] = TIMER_SECONDS

                return out

            # ---> NEW (Phase 2.8): second bad-choice zero-lives branch.
            # Desktop still prints this escalation before game-over handling.
            if (
                s == "2"
                and self.state.get("child_level_one_index", 0) == 1
                and self.state.get("lives", 0) == 1
            ):
                index = self.state.get("child_level_one_index", 0)
                character_escalates = self.state["child_level_one_character_escalates"]

                self.state["lives"] = 0

                escalation = character_escalates[index]

                index += 1
                self.state["child_level_one_index"] = index

                self.state["game_state"] = "game over"
                self.state["game_over_level"] = self.state.get("level", "one")
                self.state["stage"] = "CHILD_LEVEL_ONE_GAME_OVER"

                lines = [
                    "",
                    escalation,
                    "",
                    f"{character_name} screams, 'I don't want to be adopted by you anymore!'",
                    "",
                ]

                out = _mk_output(lines, prompt="", input_mode="MINIMAL")

                out["beats"] = [
                    [escalation],
                    [f"{character_name} screams, 'I don't want to be adopted by you anymore!'"],
                ]

                # Desktop switches to lose music at this impact moment.
                out["audio"]["bgm"] = "lose"

                return out

            # ---> NEW (Phase 2.8): third bad choice exhausts the final life.
            # There is no third character escalation in the desktop source.
            if (
                s == "2"
                and self.state.get("child_level_one_index", 0) == 2
                and self.state.get("lives", 0) == 1
            ):
                self.state["lives"] = 0
                self.state["child_level_one_index"] = 3

                self.state["game_state"] = "game over"
                self.state["game_over_level"] = self.state.get("level", "one")
                self.state["stage"] = "CHILD_LEVEL_ONE_GAME_OVER"

                lines = [
                    "",
                    f"{character_name} screams, 'I don't want to be adopted by you anymore!'",
                    "",
                ]

                out = _mk_output(lines, prompt="", input_mode="MINIMAL")

                out["beats"] = [
                    [f"{character_name} screams, 'I don't want to be adopted by you anymore!'"],
                ]

                # Desktop switches to lose music at this impact moment.
                out["audio"]["bgm"] = "lose"

                return out

            # ---> NEW (Phase 2.8.C.34): timed invalid-input retry.
            # Invalid input does NOT reset, extend, pause, or replace the
            # existing timed-choice countdown.
            if s not in ("1", "2", "__TIMEOUT__"):
                player_role = self.state.get("player_role", "")
                index = self.state.get("child_level_one_index", 0)
                bad_choices = self.state["child_level_one_bad_choices"]

                current_bad_choice = bad_choices[index]

                lines = [
                    "",
                    f"{character_name} replies, '{player_role}? I don't understand.'",
                    "",
                    "1. Put on the bracelet",
                    f"2. {current_bad_choice}",
                ]

                out = _mk_output(lines, input_mode="MINIMAL")

                # Desktop valid_input_timed() gives the invalid-response line
                # one print_pause() beat, then reprints each choice as its own beat.
                out["beats"] = [
                    [f"{character_name} replies, '{player_role}? I don't understand.'"],
                    ["1. Put on the bracelet"],
                    [f"2. {current_bad_choice}"],
                ]

                out["choices"] = [
                    {"key": "1", "line": "1. Put on the bracelet"},
                    {"key": "2", "line": f"2. {current_bad_choice}"},
                ]

                # IMPORTANT: this is the SAME timed-choice lifetime.
                # Do NOT emit choice_timeout_seconds here.
                out["meta"]["choice_timer_continues"] = True

                return out

        # ---------------------------
        # Stage: child Level 1 follow-up choice
        # ---------------------------
        if stage == "CHILD_LEVEL_ONE_FOLLOWUP":
            character_name = self.state.get("character_name", "")
            missing_parent = self.state.get("missing_parent", "")

            # ---> NEW (Phase 2.8): first authored valid_input() follow-up result.
            if s == "1":
                lines = [
                    "",
                    f"{character_name} answers, 'I would tell him to dance it off, like a puppy shakes water.'",
                    "",
                ]

                # Desktop child_level_one() marks Level 1 complete by setting level = "two".
                self.state["level"] = "two"

                # Preserve the desktop orchestration boundary:
                # level_progression() performs pause_continue() before Level 2 begins.
                self.state["stage"] = "CHILD_LEVEL_ONE_COMPLETE"

                out = _mk_output(lines, prompt="", input_mode="MINIMAL")

                out["beats"] = [
                    [f"{character_name} answers, 'I would tell him to dance it off, like a puppy shakes water.'"],
                ]

                return out

            # ---> NEW (Phase 2.8): second authored valid_input() follow-up result.
            if s == "2":
                lines = [
                    "",
                    f"'{missing_parent} would tell me to sing how I feel in my mind.'",
                    "",
                ]

                # Desktop child_level_one() marks Level 1 complete by setting level = "two".
                self.state["level"] = "two"

                # Preserve the same level_progression() boundary as follow-up choice 1.
                self.state["stage"] = "CHILD_LEVEL_ONE_COMPLETE"

                out = _mk_output(lines, prompt="", input_mode="MINIMAL")

                out["beats"] = [
                    [f"'{missing_parent} would tell me to sing how I feel in my mind.'"],
                ]

                return out

            # ---> NEW (Phase 2.8): mirror desktop valid_input() retry behavior.
            lines = [
                "",
                f"{character_name} replies, '{s}? I don't understand.'",
                "",
                "1. Ask them what they would do if their toy had a nightmare.",
                f"2. Ask them what {missing_parent} would do if they had a nightmare.",
            ]

            out = _mk_output(lines, input_mode="MINIMAL")

            out["beats"] = [
                [f"{character_name} replies, '{s}? I don't understand.'"],
                ["1. Ask them what they would do if their toy had a nightmare."],
                [f"2. Ask them what {missing_parent} would do if they had a nightmare."],
            ]

            out["choices"] = [
                {
                    "key": "1",
                    "line": "1. Ask them what they would do if their toy had a nightmare.",
                },
                {
                    "key": "2",
                    "line": f"2. Ask them what {missing_parent} would do if they had a nightmare.",
                },
            ]

            return out

        # For now, no invented continuation. (Next Phase will route into the next authored slice.)
        return _mk_output([])