# ============================================================
# CHAPTER 0 — Imports & Platform Setup
# ============================================================

# --- Standard library ---
import os
import platform
import random
import shutil
import subprocess
import sys
import math
import time
from typing import Optional

# --- Third-party ---
import pygame
from colorama import Back, Fore, init

# --- Platform-specific input polling ---
# Windows uses msvcrt; macOS/Linux use select for stdin polling.
if platform.system() == "Windows":
    import msvcrt
else:
    import select

# Color output defaults (we still explicitly reset in key places)
init(autoreset=True)


def enable_vt_mode():
    """Enable ANSI escape code handling on Windows terminals."""
    if platform.system() != "Windows":
        return
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        h = kernel32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE = -11
        mode = ctypes.c_uint()
        if kernel32.GetConsoleMode(h, ctypes.byref(mode)):
            # ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
            kernel32.SetConsoleMode(h, mode.value | 0x0004)
    except Exception:
        pass


enable_vt_mode()

def _strip_ansi(s: str) -> str:
    """
    Remove ANSI escape sequences from a string.
    Used ONLY for layout math (never for visible output).
    """
    import re
    ansi_escape = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
    return ansi_escape.sub("", s)


# -------------------------
# Windows-only: force-hide the *real* console cursor (prevents ghost blink at top-left)
# -------------------------
def _win_set_cursor_visible(visible: bool) -> None:
    """
    Best-effort Windows API cursor visibility control.
    Stronger than ANSI \x1b[?25l for terminals that ignore hide/blink.
    """
    if platform.system() != "Windows":
        return
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        h = kernel32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE

        class CONSOLE_CURSOR_INFO(ctypes.Structure):
            _fields_ = [("dwSize", ctypes.c_uint), ("bVisible", ctypes.c_bool)]

        info = CONSOLE_CURSOR_INFO()
        if kernel32.GetConsoleCursorInfo(h, ctypes.byref(info)):
            info.bVisible = bool(visible)
            kernel32.SetConsoleCursorInfo(h, ctypes.byref(info))
    except Exception:
        pass

# ============================================================
# CHAPTER 1 — Audio System (pygame mixer, channels, sound keys)
# ============================================================


pygame.mixer.init()
pygame.mixer.set_num_channels(8)

music_on = True

# --- Mixer channels ---
# Background music (muted when music_on is False)
BG_CH = pygame.mixer.Channel(0)

# SFX (NOT affected by music_on)
SFX_CH = pygame.mixer.Channel(1)

# Pause loop channel (SFX; NOT affected by music_on)
PAUSE_CH = pygame.mixer.Channel(2)

SFX_CH.set_volume(1.0)  # punchy


# -------------------------
# Sound Assets
# -------------------------
SFX_KEYS = [
    "avalanche",
    "exhale",
    "wind",
    "boot",
    "lake",
    "bait",
    "fish",
    "campfire",
]

SFX_SOUNDS = {
    "avalanche": pygame.mixer.Sound("1_avalanche.ogg"),
    "exhale":    pygame.mixer.Sound("2_exhale.ogg"),
    "wind":      pygame.mixer.Sound("3_wind.ogg"),
    "boot":      pygame.mixer.Sound("4_boot.ogg"),
    "lake":      pygame.mixer.Sound("5_lake.ogg"),
    "bait":      pygame.mixer.Sound("6_bait.ogg"),
    "fish":      pygame.mixer.Sound("7_fish.ogg"),
    "campfire":  pygame.mixer.Sound("8_campfire.ogg"),
}

PAUSE_SOUNDS = {
    "wolf_close": pygame.mixer.Sound("0_wolf_close.ogg"),
    "wolf_far":   pygame.mixer.Sound("0_wolf_far.ogg"),
}

SOUNDS = {
    "menu": pygame.mixer.Sound("main_menu.ogg"),
    "level1": pygame.mixer.Sound("level_one_gameplay.ogg"),
    "level2": pygame.mixer.Sound("level_two_gameplay.ogg"),
    "bonus_intro": pygame.mixer.Sound("bonus_scene_intro.ogg"),
    "bonus_loop": pygame.mixer.Sound("bonus_scene_loop.ogg"),
    "win": pygame.mixer.Sound("game_won.ogg"),
    "lose": pygame.mixer.Sound("game_over.ogg"),
}


# -------------------------
# Background Music State
# -------------------------
current_bg_key = None
pending_loop_key = None

# "Desired" keys are remembered even when music is OFF,
# so toggling music back ON can resume correctly.
desired_bg_key = None
desired_pending_key = None

# Which gameplay track we consider "active" for resume fallbacks
active_gameplay_track = "level1"


# -------------------------
# Background Music Controls
# -------------------------
def bg_stop():
    global current_bg_key, pending_loop_key
    BG_CH.stop()
    current_bg_key = None
    pending_loop_key = None


def bg_play(key, loop=True):
    global current_bg_key, desired_bg_key, desired_pending_key

    # Always remember what SHOULD be playing, even if music is off.
    desired_bg_key = key
    desired_pending_key = None

    if not music_on:
        return

    if current_bg_key == key and BG_CH.get_busy():
        return

    bg_stop()
    loops = -1 if loop else 0
    BG_CH.play(SOUNDS[key], loops=loops)
    current_bg_key = key


def bg_intro_then_loop(intro_key, loop_key):
    global current_bg_key, pending_loop_key, desired_bg_key, desired_pending_key

    # Always remember what SHOULD be playing, even if music is off.
    desired_bg_key = intro_key
    desired_pending_key = loop_key

    if not music_on:
        return

    bg_stop()
    BG_CH.play(SOUNDS[intro_key], loops=0)
    current_bg_key = intro_key
    pending_loop_key = loop_key


def bg_update():
    global current_bg_key, pending_loop_key

    if not music_on:
        return

    # If we finished the intro, start the loop
    if pending_loop_key and not BG_CH.get_busy():
        BG_CH.play(SOUNDS[pending_loop_key], loops=-1)
        current_bg_key = pending_loop_key
        pending_loop_key = None


def music_enable():
    global music_on
    music_on = True
    BG_CH.set_volume(1.0)


def music_disable():
    global music_on
    music_on = False
    BG_CH.set_volume(0.0)
    bg_stop()


# ============================================================
# CHAPTER 2 — Input Layer (Keyboard + Timed Input)
# ============================================================

# [2.5.A] Windows escape/extended-key swallowing
def _eat_ansi_escape_windows():
    """
    Best-effort: consume an ANSI escape sequence that starts with ESC.
    This prevents mouse wheel / arrow / terminal mouse-reporting sequences
    from leaking printable chars into the player's input buffer.
    Windows terminals sometimes emit: ESC [ ... (ends with a letter or ~)
    """
    if platform.system() != "Windows":
        return

    # Give the terminal a tiny moment to deliver the rest of the sequence
    time.sleep(0.001)

    seq = ""
    # Consume a short sequence safely (we don't want to block forever)
    for _ in range(64):
        if not msvcrt.kbhit():
            break
        ch2 = msvcrt.getwch()
        seq += ch2

        # Most CSI sequences end with a letter (A–Z/a–z) or tilde (~)
        if ch2.isalpha() or ch2 == "~":
            break

# [2.6.A] Windows: drain any pending keypresses (mouse wheel / arrows / ANSI junk)
def _flush_pending_input_windows():
    """
    Clears any pending characters already waiting in the Windows console input buffer.
    Prevents mouse wheel / arrow sequences from "typing themselves" into the next prompt.
    """
    if platform.system() != "Windows":
        return

    # Drain everything that's already queued up
    while msvcrt.kbhit():
        ch = msvcrt.getwch()

        # Extended key prefix: swallow its follow-up byte if present
        if ch in ("\x00", "\xe0"):
            if msvcrt.kbhit():
                msvcrt.getwch()
            continue

        # ANSI escape sequence (ESC ...)
        if ch == "\x1b":
            _eat_ansi_escape_windows()
            continue

        # Otherwise: just discard it
        continue

# -------------------------
# SFX Controls
# -------------------------
sfx_index = 0

def play_enter_sfx():
    """
    Each Enter press plays the next SFX once.
    Cycles continuously through 1–8.
    NOT affected by music_on.
    """
    global sfx_index

    key = SFX_KEYS[sfx_index]

    SFX_CH.stop()
    SFX_CH.play(SFX_SOUNDS[key], loops=0)

    sfx_index = (sfx_index + 1) % len(SFX_KEYS)

# Generic one-shot SFX helper
def play_sfx(filename: str):
    """
    Play a one-shot sound effect on the SFX channel.
    Not affected by music_on.
    """
    try:
        sound = pygame.mixer.Sound(filename)
        SFX_CH.stop()
        SFX_CH.play(sound, loops=0)
    except Exception:
        pass

# Semantic wrapper for pressure events
def play_timer_zero_sfx():
    """
    Play a random SFX when the decision timer reaches zero.
    This represents pressure / loss of control, not a user-entered action.
    """
    try:
        sfx = random.choice([
            "00_air_pressure.ogg",
            "00_turbulence.ogg",
        ])
        play_sfx(sfx)
    except Exception:
        pass


# -------------------------
# Pause Wolf Ambience
# -------------------------
def pause_wolf_start():
    """Start looping wolf ambience on PAUSE_CH (NOT affected by music_on)."""
    choice = random.choice(["wolf_close", "wolf_far"])
    PAUSE_CH.fadeout(500)
    PAUSE_CH.play(PAUSE_SOUNDS[choice], loops=-1)


def pause_wolf_stop():
    """Stop looping wolf ambience."""
    PAUSE_CH.fadeout(500)

def log_prompt_prefix_once(prompt: str):
    """
    If a prompt is multi-line (e.g. "What's their name?\n> "),
    store ONLY the lines ABOVE the final input line into STORY_LOG,
    so redraw_story() can bring the question back after pause/resume.

    We do NOT print or sleep here. This is log-only.
    """
    # Never log prompts inside pause menu
    if in_pause_menu:
        return

    # Only log gameplay prompts (menus set pause_enabled = False)
    if not pause_enabled:
        return

    # Split into visual lines (keep \n)
    lines = prompt.splitlines(True)
    if len(lines) < 2:
        return

    # If the last line is the input line ("> " or starts with ">")
    last = lines[-1]
    if not last.lstrip().startswith(">"):
        return

    prefix_lines = lines[:-1]  # everything above the input line
    if not "".join(prefix_lines).strip():
        return

    # Log each prefix line as a PROMPT line so redraw prints it WHITE.
    for ln in prefix_lines:
        # Ensure each stored line ends with exactly one newline
        clean = ln.rstrip("\n") + "\n"
        STORY_LOG.append(PROMPT_LOG_MARKER + clean)  # <-- marker is the key

    # Keep memory bounded (do it per-line, since we append per-line)
    if len(STORY_LOG) > MAX_LOG_LINES:
        STORY_LOG.pop(0)

    _clamp_story_scroll()

# [2.5.B] Untimed input (supports SPACE-to-pause + story scroll keys)
def input_with_audio(prompt):
    """
    Like input(), but keeps calling bg_update() so intro->loop transitions
    still happen while we wait for the player to press Enter / type.
    Also allows SPACE-to-pause (only when pause_enabled is True).
    """
    # IMPORTANT:
    # If prompt is multi-line like "What's their name?\n> ",
    # we log ONLY the question line(s) into STORY_LOG so redraw_story()
    # can restore them after pause/resume.
    global pause_enabled, in_pause_menu, prompt_prefix_logged
    global last_ext_prefix_time, last_scroll_time, last_scroll_redraw_time
    global pulses_fired, pulse_marks

    buffer = ""

    # Ensure we only log the prompt prefix ONCE per prompt call
    prompt_prefix_logged = False
    
    # --- Log prompt prefix (question lines) into STORY_LOG one time ---
    if not prompt_prefix_logged:
        log_prompt_prefix_once(prompt)   # Makes "What's their name?" survive redraw
        prompt_prefix_logged = True

        # Make sure the prompt line starts "clean" (white), regardless of what was printed before.
    sys.stdout.write("\x1b[0m")
    sys.stdout.flush()

    # Print the authored prompt ONCE.
    print(prompt, end="", flush=True)

    # From here onward, NEVER print real newlines for the pause hint (prevents stacking/jumping).
    # Reserve a dedicated status line directly under the input line, like timed input does.
    prompt_last_line = prompt.split("\n")[-1]

    _reserve_status_line_below_input()

    _timed_line_render(prompt_last_line, buffer, None)

    # -------- Windows --------
    if platform.system() == "Windows":
        _flush_pending_input_windows()  # prevent àPàH junk from prior scroll events

        awaiting_ext_code = False  # follow-up byte after \x00/\xe0
        last_ext_prefix_time = 0.0   # when we last saw \x00/\xe0
        last_scroll_time = 0.0       # when we last handled H/P as scroll
        last_scroll_redraw_time = 0.0  # throttle redraws to reduce flicker

        # Level 1 anger pulses: EXACTLY TWO per timed choice prompt (no RNG)
        pulses_fired = set()         # stores seconds-left marks we've already fired on
        pulse_marks = []             # planned seconds-left marks to fire on

        while True:
            bg_update()
            time.sleep(0.02)

            if msvcrt.kbhit():
                ch = msvcrt.getwch()

                # If last key was an extended prefix, this char is the follow-up code ("H"/"P"/etc).
                if awaiting_ext_code:
                    awaiting_ext_code = False

                    # Only allow scroll + redraw during ACTIVE gameplay prompts
                    # (Never inside pause_menu; never in menus; never when pause is disabled)
                    if game_state == "running" and pause_enabled and (not in_pause_menu):
                        if ch in ("H", "P"):
                            if ch == "H":
                                scroll_story(+3)
                            else:  # "P"
                                scroll_story(-3)
                            last_scroll_time = time.time()

                            # Drain any extra bytes left by the terminal scroll sequence.
                            _flush_pending_input_windows()

                            # Throttle rapid wheel events to reduce flicker.
                            now_redraw = time.time()
                            if now_redraw - last_scroll_redraw_time < 0.12:
                                continue
                            last_scroll_redraw_time = now_redraw

                            wipe_visible_soft() # less flicker than wipe_visible() for scroll redraws

                            if level == "one":
                                title_banner()

                            redraw_story()

                            sys.stdout.write("\x1b[0m")
                            sys.stdout.flush()

                            # DO NOT re-print the full prompt (it causes duplication/stacks).
                            # Only re-render the input line + status line.
                            sys.stdout.write(prompt_last_line)
                            sys.stdout.flush()

                            _reserve_status_line_below_input()

                            _timed_line_render(prompt_last_line, buffer, None)

                    # ALWAYS swallow the follow-up byte
                    continue

                # If the terminal scrollwheel leaves a stray printable 'H'/'P' behind (sometimes without the
                # leading extended-code prefix), treat it as scroll so we never print ghost letters.
                if ch in ("H", "P") and game_state == "running" and pause_enabled and (not in_pause_menu):
                    if buffer == "":
                        if ch == "H":
                            scroll_story(+3)
                        else:  # "P"
                            scroll_story(-3)
                        last_scroll_time = time.time()

                        # Drain any extra bytes left by the terminal scroll sequence.
                        _flush_pending_input_windows()

                        # Throttle rapid wheel events to reduce flicker.
                        now_redraw = time.time()
                        if now_redraw - last_scroll_redraw_time < 0.12:
                            continue
                        last_scroll_redraw_time = now_redraw

                        wipe_visible_soft()  # less flicker than wipe_visible() for scroll redraws

                        if level == "one":
                            title_banner()

                        redraw_story()

                        sys.stdout.write("\x1b[0m")
                        sys.stdout.flush()

                        # Only re-render the input line + status line (no full prompt reprint).
                        sys.stdout.write(prompt_last_line)
                        sys.stdout.flush()

                        _reserve_status_line_below_input()

                        _timed_line_render(prompt_last_line, buffer, None)
                        continue

                # SPACE = pause (only during gameplay)
                if ch == " " and pause_enabled and not in_pause_menu:
                    # Clear our 2-line UI region cleanly before entering pause menu
                    _timed_line_clear()

                    pause_menu()  # returns when player chooses Continue

                    wipe_visible()

                    if level == "one":
                        title_banner()  # restore lvl 1 banner after pause menu

                    redraw_story()

                    sys.stdout.write("\x1b[0m")
                    sys.stdout.flush()

                    # DO NOT re-print the full prompt.
                    # Re-render only the input UI line + status line.
                    sys.stdout.write(prompt_last_line)
                    sys.stdout.flush()

                    _reserve_status_line_below_input()

                    _timed_line_render(prompt_last_line, buffer, None)
                    continue

                if ch in ("\r", "\n"):
                    entered = buffer.strip()

                    # "Commit" what the player typed onto the transcript line
                    # (so it doesn't vanish until a redraw_story happens)
                    if sys.stdout.isatty():
                        sys.stdout.write("\x1b[0m")
                        sys.stdout.write("\r\x1b[2K" + f"{prompt_last_line}{entered}")
                        # clear the status line below
                        sys.stdout.write("\x1b[B\r\x1b[2K\x1b[A")
                        # finish on a real newline so the next printed story line behaves normally
                        sys.stdout.write("\r\n")
                        sys.stdout.flush()
                    else:
                        print(f"{prompt_last_line}{entered}")

                    play_enter_sfx()
                    log_player_input(entered)
                    return entered

                if ch == "\b":
                    if buffer:
                        buffer = buffer[:-1]
                        _timed_line_render(prompt_last_line, buffer, None)  # keep UI stable
                    continue

                # Extended key prefix (\x00 / \xe0) -> next getwch() is a follow-up code (H/P/etc)
                if ch in ("\x00", "\xe0"):
                    awaiting_ext_code = True
                    last_ext_prefix_time = time.time()
                    continue

                # ESC -> eat ANSI sequence (mouse wheel / arrows in some terminals)
                if ch == "\x1b":
                    _eat_ansi_escape_windows()
                    continue

                # Ignore other non-printable control chars
                if ord(ch) < 32:
                    continue

                # If the terminal leaked a stray scroll code ('H'/'P') without the prefix byte,
                # swallow it briefly after scroll-related activity (prevents ghost letters).
                now = time.time()
                if ch in ("H", "P") and (now - last_ext_prefix_time < 1.00 or now - last_scroll_time < 1.00):
                    continue

                # Normal character
                buffer += ch
                _timed_line_render(prompt_last_line, buffer, None)  # keep UI stable


    # -------- macOS/Linux --------
    else:
        while True:
            bg_update()
            time.sleep(0.02)

            rlist, _, _ = select.select([sys.stdin], [], [], 0)
            if rlist:
                line = sys.stdin.readline()
                play_enter_sfx()
                return line.strip()


def _reserve_status_line_below_input():
    """
    Reserve ONE real blank line below the current input line to use as the status line.

    Why:
    - Using only ANSI cursor-down ("\x1b[B") can trigger terminal auto-scroll when the
      prompt is on the last visible row, which makes the anger glyph overwrite mis-target.
    - This creates a real line once, then moves back up so the cursor stays on the input line.
    """
    if not sys.stdout.isatty():
        return

    # Create a real line below (status line), clear it, then return to input line.
    # This prevents "\x1b[B" inside _timed_line_render from causing scroll.
    sys.stdout.write("\n\r\x1b[2K\x1b[A")
    sys.stdout.flush()


# [2.5.C] Timed-input UI rendering helpers (input line + status line)
def _timed_line_render(prompt_last_line: str, buffer: str, seconds_left: Optional[int]):
    """
    Renders player input on its own line, and renders timer / pause hint
    on a SINGLE status line directly RIGHT BELOW it.

    Cursor always stays on the input line.
    """
    # IMPORTANT:
    # - This must NOT print real newlines every frame, or the terminal will "grow"
    #   and the screen will jump/scroll.
    # - We update the status line using cursor moves (down/up), not '\n'.
    if not sys.stdout.isatty():
        return

    timer_text = f"⏳ {seconds_left:02d}s" if seconds_left is not None else ""
    pause_text = "(Press SPACE to pause)" if (pause_enabled and not in_pause_menu) else ""
    parts = [p for p in (timer_text, pause_text) if p]
    status = "   ".join(parts)

    # Force default styling so typed input stays white.
    sys.stdout.write("\x1b[0m")

    # 1) Rewrite input line (no newline)
    sys.stdout.write("\r\x1b[2K" + f"{prompt_last_line}{buffer}")

    # 2) Update the status line BELOW, WITHOUT emitting a real newline.
    # Move down 1 row, clear that line, write status.
    sys.stdout.write("\x1b[B\r\x1b[2K" + status)

    # 3) Move back up to input line, re-place cursor after buffer.
    sys.stdout.write("\x1b[A\r\x1b[2K" + f"{prompt_last_line}{buffer}")

    sys.stdout.flush()

def _timed_line_clear():
    """
    Clear the timed-input 2-line UI region (input line + status line) without
    adding extra lines to the terminal.
    """
    if not sys.stdout.isatty():
        return

    # Clear input line
    sys.stdout.write("\r\x1b[2K")

    # Clear status line (move down 1, clear, then move back up)
    sys.stdout.write("\x1b[B\r\x1b[2K\x1b[A")

    # Reset terminal state after cursor tricks
    sys.stdout.write("\x1b[0m\x1b[?25h")

    # Finish on a clean new line so future prints behave normally
    sys.stdout.write("\r\n")
    sys.stdout.flush()

# ------------------------------------------------------------
# Screen clearing toolbox (preferred order)
# ------------------------------------------------------------
# 1) wipe_visible(): fast ANSI clear+home of the current buffer (best-effort).
#    Use for most transitions when you just need the visible screen clean.
# 2) screen_reset(): heavier "visible wipe" strategy (optionally pushes lines).
#    Use when the terminal is being stubborn and old content is lingering.
# 3) force_hard_clear(): sledgehammer reset (push lines + ANSI + external clear).
#    Use when things are REALLY weird across terminals (VS Code / Git Bash / etc).
# 4) clear_screen(): legacy helper. Keep for compatibility, but prefer the tools above.
#
# NOTE: none of these can *guarantee* scrollback behavior across all terminals.
# The goal is consistent *visible* screens during gameplay.
def screen_reset(scrollback: bool = False, push_lines: bool = True):
    """
    Visible-screen wipe that works even when ANSI clear / 'clear' / 'cls' are flaky.
    Strategy:
      1) (Optional) Print enough newlines to push old content off the visible screen.
      2) Attempt ANSI clear + home (+ optional scrollback clear).
      3) Attempt external clear command as a fallback.
    """
    # 1) Push old content off-screen
    # NOTE: this pollutes terminal scrollback.
    if push_lines:
        try:
            rows = shutil.get_terminal_size((80, 25)).lines
        except Exception:
            rows = 40
        print("\n" * (rows + 10), end="", flush=True)

    # 2) ANSI clear attempts (best-effort)
    try:
        if scrollback:
            sys.stdout.write("\x1b[2J\x1b[H\x1b[3J")
        else:
            sys.stdout.write("\x1b[2J\x1b[H")
        sys.stdout.write("\x1b[0m\x1b[?25h")  # reset attrs, show cursor
        sys.stdout.flush()
    except Exception:
        pass

    # 3) External clear as fallback (works better than os.system sometimes)
    try:
        if platform.system() == "Windows":
            # Git Bash / MSYS / mintty generally likes 'clear'
            cmd = "clear" if (os.environ.get("MSYSTEM") or os.environ.get("TERM")) else "cls"
        else:
            cmd = "clear"
        subprocess.run(cmd, shell=True)
    except Exception:
        pass


def force_hard_clear():
    """
    Best-effort hard reset for terminals that behave weirdly (Git Bash / VS Code / etc).
    Strategy:
      1) Push old content off the visible screen (works even if clear is flaky)
      2) ANSI clear + home (+ scrollback clear)
      3) Shell clear fallback
      4) ANSI clear again (some terminals only behave after the shell clear)
    """
    # 1) Push old content off-screen no matter what terminal we're in
    try:
        rows = shutil.get_terminal_size((80, 25)).lines
    except Exception:
        rows = 40

    try:
        print("\n" * (rows + 15), end="", flush=True)
    except Exception:
        pass

    # 2) ANSI clear (screen + home + scrollback) — do this even if isatty lies
    try:
        sys.stdout.write("\x1b[0m\x1b[?25h\x1b[2J\x1b[H\x1b[3J")
        sys.stdout.flush()
    except Exception:
        pass

    # 3) External clear as fallback — Git Bash/MSYS usually wants "clear"
    try:
        if platform.system() == "Windows":
            cmd = "clear" if (os.environ.get("MSYSTEM") or os.environ.get("TERM")) else "cls"
        else:
            cmd = "clear"
        subprocess.run(cmd, shell=True)
    except Exception:
        pass

    # 4) One more ANSI pass after shell clear
    try:
        sys.stdout.write("\x1b[0m\x1b[?25h\x1b[2J\x1b[H")
        sys.stdout.flush()
    except Exception:
        pass

def enter_alt_screen():
    """
    Use the terminal's alternate screen buffer (best-effort).
    Goal: make each "screen" start blank and reduce old text lingering above.
    """
    # NOTE: not all terminals honor the alt buffer sequence consistently.
    global _alt_screen
    if _alt_screen:
        return
    try:
        sys.stdout.write("\x1b[?1049h")   # enter alt buffer
        sys.stdout.write("\x1b[2J\x1b[H") # clear + home
        sys.stdout.write("\x1b[0m\x1b[?25h")
        sys.stdout.flush()
        _alt_screen = True
    except Exception:
        _alt_screen = False


def exit_alt_screen():
    """Return to the normal terminal buffer."""
    global _alt_screen
    if not _alt_screen:
        return
    try:
        sys.stdout.write("\x1b[?1049l")   # exit alt buffer
        sys.stdout.write("\x1b[0m\x1b[?25h")
        sys.stdout.flush()
    except Exception:
        pass
    _alt_screen = False

def wipe_visible():
    """
    Best-effort visible wipe inside the current buffer (ANSI clear + home).
    Prefer this for most transitions (game over / retry / level change) when you
    just need the visible screen clean.
    """
    # NOTE: some terminals may not fully honor ANSI clears;
    # use screen_reset()/force_hard_clear() if needed.
    try:
        sys.stdout.write("\x1b[0m\x1b[?25h\x1b[2J\x1b[H")
        sys.stdout.flush()
    except Exception:
        pass

def wipe_visible_soft():
    """
    Softer wipe for scroll-redraw during prompts.
    Clears from home to end of screen without the heavier full-buffer clear.
    Reduces flicker on mouse-wheel / PgUp/PgDn redraws.
    """
    try:
        sys.stdout.write("\x1b[0m\x1b[?25h\x1b[H\x1b[J")
        sys.stdout.flush()
    except Exception:
        pass

# ============================================================
# Level 1 Emote Effect (ANGER): brief blur -> clear (will update chapter numbering later)
# ============================================================

# Characters we can swap in to simulate "tunnel vision" distortion.
_ANGER_GLYPHS = list("~^*#/\\|_-+=?!:;.,'`")


def _corrupt_text_keep_len(s: str, intensity: float = 0.14) -> str:
    """
    Returns a corrupted version of s with the SAME LENGTH.
    We only replace some characters (not spaces/newlines) to simulate blur.
    """
    out = []
    for ch in s:
        if ch in ("\n", "\r"):
            out.append(ch)
            continue

        if ch == " ":
            out.append(" ")
            continue

        # Keep digits and the "1./2." prefix mostly readable by biasing away from corruption.
        if ch.isdigit() or ch in ".>":
            if random.random() < (intensity * 0.25):
                out.append(random.choice(_ANGER_GLYPHS))
            else:
                out.append(ch)
            continue

        # Normal letters/punctuation: corrupt at intensity rate
        if random.random() < intensity:
            out.append(random.choice(_ANGER_GLYPHS))
        else:
            out.append(ch)

    return "".join(out)


def _find_last_choice_pair_indices():
    """
    Find the most recent pair of STORY_LOG entries that visually look like:
      (optional leading whitespace/newlines) + "1. ..."
      (optional leading whitespace/newlines) + "2. ..."
    Returns (idx1, idx2) or (None, None) if not found.
    """
    import re

    def is_choice_line(s: str, n: int) -> bool:
        # Accept leading newlines/spaces because print_pause() may store "\n1. ..." etc.
        return re.match(rf"^\s*{n}\.\s", s) is not None

    idx2 = None
    idx1 = None

    # Scan backward to find the last "2. " line (allowing leading whitespace/newlines)
    for i in range(len(STORY_LOG) - 1, -1, -1):
        chunk = STORY_LOG[i]
        if isinstance(chunk, str) and is_choice_line(chunk, 2):
            idx2 = i
            break

    if idx2 is None:
        return (None, None)

    # Then scan backward from idx2 to find the nearest preceding "1. "
    for j in range(idx2 - 1, -1, -1):
        chunk = STORY_LOG[j]
        if isinstance(chunk, str) and is_choice_line(chunk, 1):
            idx1 = j
            break

    return (idx1, idx2)


def _anger_pulse_choices_redraw(prompt: str, prompt_last_line: str, buffer: str, seconds_left: Optional[int]):
    """
    Anger emote (LEVEL 1 ONLY):

    IMPORTANT BEHAVIOR:
    - Comic-book emotional censorship distortion of ONLY the *current* moral/timed choice pair text ("1. ...", "2. ...")
    - NEVER permanently edits STORY_LOG
    - NEVER wipes/redraws the full screen (no full-terminal flicker)
    - Skips while player is scrolled up (can't safely target the on-screen choice lines)
    """
    global story_scroll_offset_lines
    global last_scroll_time

    # Only on interactive terminals (our redraw relies on ANSI cursor control)
    if not sys.stdout.isatty():
        return

    # If player scrolled up, we can't safely assume where the choice lines are on screen.
    if story_scroll_offset_lines != 0:
        return

    # If the player just scrolled/redrew, skip this pulse (prevents mis-targeting / stray letters).
    if (time.time() - last_scroll_time) < 0.35:
        return

    idx1, idx2 = _find_last_choice_pair_indices()
    if idx1 is None or idx2 is None:
        return

    # Only animate the *current* choice block (the most recent 1/2 lines).
    # This prevents rare cases where an older 1/2 pair is found and we scribble the wrong lines.
    if not (idx2 == len(STORY_LOG) - 1 and idx1 == len(STORY_LOG) - 2):
        return

    original_1 = str(STORY_LOG[idx1])
    original_2 = str(STORY_LOG[idx2])

    # Keep pulses VERY short so the timer remains readable.
    PULSE_SECONDS_EACH = 0.10
    INTENSITY = 0.22

    # Build corrupted display-only lines (DON'T mutate STORY_LOG)
    corrupt_1 = _corrupt_text_keep_len(original_1, intensity=INTENSITY)
    corrupt_2 = _corrupt_text_keep_len(original_2, intensity=INTENSITY)

    def _clip_no_wrap(s: str) -> str:
        # Never allow embedded newlines during in-place rewrites.
        s = s.replace("\r", "").replace("\n", "")
        cols = shutil.get_terminal_size((80, 24)).columns
        if cols and len(s) >= cols:
            # Keep 1 column free so we don't wrap at the last cell.
            s = s[: max(0, cols - 2)] + "…"
        return s

    def _paint_choice_line(s: str) -> str:
        # Keep choice lines BLUE for the entire effect.
        return Back.BLACK + Fore.LIGHTBLUE_EX + _clip_no_wrap(s) + "\x1b[0m"

    def _overwrite_choice_block(line1: str, line2: str) -> None:
        """
        Assumes cursor is currently on the input line (prompt line).
        Layout immediately above the prompt:
            1. ...
            2. ...
            >  [cursor here]

        IMPORTANT:
        - Avoid \x1b[2K clears during animation. Some terminals visibly "blink" the cleared line
        before the rewrite lands, which looks like option 2 disappearing.
        - Instead: overwrite + pad with spaces (while still avoiding wrap).
        """

        cols = shutil.get_terminal_size((80, 24)).columns

        def _write_overpainted_choice_line(s: str) -> None:
            # Clip first so we never wrap; then pad to cover leftovers from the prior render.
            clipped = _clip_no_wrap(s)
            visible_len = len(clipped)

            painted = Back.BLACK + Fore.LIGHTBLUE_EX + clipped + "\x1b[0m"

            # Leave 1 column free so we never hit the terminal's wrap edge.
            pad_len = max(0, (cols - 2) - visible_len)
            sys.stdout.write("\r" + painted + (" " * pad_len))

        # Ensure we start from column 0 on the input line
        sys.stdout.write("\r")

        # Up 2 -> line "1."
        sys.stdout.write("\x1b[2A")
        _write_overpainted_choice_line(line1)

        # Down 1 -> line "2."
        sys.stdout.write("\x1b[1B")
        _write_overpainted_choice_line(line2)

        # Down 1 -> back to the prompt line (and reset to column 0)
        sys.stdout.write("\x1b[1B\r")
        sys.stdout.flush()

        # Re-render input + status UI so the cursor stays where the player is typing
        _timed_line_render(prompt_last_line, buffer, seconds_left)

    # Pulse #1 (corrupt -> clean)
    _overwrite_choice_block(corrupt_1, corrupt_2)
    time.sleep(PULSE_SECONDS_EACH)
    _overwrite_choice_block(original_1, original_2)

    # Pulse #2 (corrupt -> clean)
    _overwrite_choice_block(corrupt_1, corrupt_2)
    time.sleep(PULSE_SECONDS_EACH)
    _overwrite_choice_block(original_1, original_2)

    # Restore timer/status UI (and keep cursor on prompt line)
    _timed_line_render(prompt_last_line, buffer, seconds_left)


def _fear_shiver_choices_redraw(prompt: str, prompt_last_line: str, buffer: str, seconds_left: Optional[int]):
    """
    Fear emote (LEVEL 2 ONLY):

    Design goals:
    - Affect ONLY the *current* moral/timed choice pair text ("1. ...", "2. ...")
    - Coordinated "earthquake" tremor: line 1 and line 2 trade indentation (opposite sway)
    - Micro-variation (not metronomic) so it doesn't become predictable
    - NEVER permanently edits STORY_LOG
    - NEVER wipes/redraws the full screen
    - Skips while player is scrolled up (can't safely target the on-screen choice lines)
    """
    global story_scroll_offset_lines
    global last_scroll_time

    # Only on interactive terminals (our redraw relies on ANSI cursor control)
    if not sys.stdout.isatty():
        return

    # If player scrolled up, we can't safely assume where the choice lines are on screen.
    if story_scroll_offset_lines != 0:
        return

    # If the player just scrolled/redrew, skip this pulse (prevents mis-targeting / stray letters).
    if (time.time() - last_scroll_time) < 0.35:
        return

    idx1, idx2 = _find_last_choice_pair_indices()
    if idx1 is None or idx2 is None:
        return

    # Only animate the *current* choice block (the most recent 1/2 lines).
    if not (idx2 == len(STORY_LOG) - 1 and idx1 == len(STORY_LOG) - 2):
        return

    original_1 = str(STORY_LOG[idx1])
    original_2 = str(STORY_LOG[idx2])

    # Same “arrival/exit” feel as Level 1: fast, readable, but stressful.
    # One pulse = a few rapid frames, then restore clean lines.
    FRAME_SLEEP_BASE = 0.040   # ~40ms
    FRAMES_PER_PULSE = 6

    def _clip_no_wrap(s: str) -> str:
        s = s.replace("\r", "").replace("\n", "")
        cols = shutil.get_terminal_size((80, 24)).columns
        if cols and len(s) >= cols:
            # Keep 1 column free so we don't wrap at the last cell.
            s = s[: max(0, cols - 2)] + "…"
        return s

    def _paint_choice_line(s: str) -> str:
        return Back.BLACK + Fore.LIGHTBLUE_EX + _clip_no_wrap(s) + "\x1b[0m"

    def _overwrite_choice_block(line1: str, line2: str) -> None:
        """
        Assumes cursor is currently on the input line (prompt line).
        """
        # IMPORTANT:
        # - We avoid line-clears that can "blink" and look like disappearing options.
        # - We overwrite + pad with spaces to fully cover prior content (no wrap).
        
        cols = shutil.get_terminal_size((80, 24)).columns

        def _write_overpainted_choice_line(s: str) -> None:
            clipped = _clip_no_wrap(s)
            visible_len = len(clipped)
            painted = Back.BLACK + Fore.LIGHTBLUE_EX + clipped + "\x1b[0m"

            # Leave 1 column free so we never hit terminal wrap edge.
            max_len = max(0, (cols - 1) if cols else visible_len)
            pad = " " * max(0, max_len - visible_len)

            sys.stdout.write("\r" + painted + pad)

        # Ensure we start from column 0 on the input line
        sys.stdout.write("\r")

        # Up 2 -> line "1."
        sys.stdout.write("\x1b[2A")
        _write_overpainted_choice_line(line1)

        # Down 1 -> line "2."
        sys.stdout.write("\x1b[1B")
        _write_overpainted_choice_line(line2)

        # Down 1 -> back to the prompt line
        sys.stdout.write("\x1b[1B\r")
        sys.stdout.flush()

        # Force the input + status UI to be correct after the overwrite.
        _timed_line_render(prompt_last_line, buffer, seconds_left)

    def _indent(s: str, n: int) -> str:
        # Shifts the entire line right by n spaces.
        # (Opposite sway is achieved by trading indent amounts between the two lines.)
        if n <= 0:
            return s
        return (" " * n) + s

    # Build a tremor pattern that is constant pressure but not perfectly predictable.
    # We trade indents: (2,0) <-> (0,2), with occasional (1,0)/(0,1) mixed in.
    patterns = [(2, 0), (0, 2), (2, 0), (0, 2), (1, 0), (0, 1)]
    random.shuffle(patterns)

    # Run the tremor frames (fast), then restore clean lines.
    for i in range(FRAMES_PER_PULSE):
        a, b = patterns[i % len(patterns)]

        # micro-variation in timing, but tiny (so it doesn't become “cold shiver”)
        dt = FRAME_SLEEP_BASE + random.uniform(-0.010, 0.010)

        _overwrite_choice_block(_indent(original_1, a), _indent(original_2, b))
        time.sleep(max(0.010, dt))

    # Restore clean lines at the end of the pulse
    _overwrite_choice_block(original_1, original_2)
    _timed_line_render(prompt_last_line, buffer, seconds_left)


# [2.5.D] Timed input (live timer toggle + true pause-freeze)
def input_with_audio_timeout(prompt: str, timeout_seconds: int, default_choice: str = "2") -> str:
    """
    Like input_with_audio(), but can show a visible countdown timer.

    Behavior:
    - If timers_on is True, counts down from timeout_seconds to 0 and returns "__TIMEOUT__" at 0.
    - If timers_on is False, acts like normal input BUT still keeps the "(Press SPACE to pause)" hint visible.
    - If timers_on is toggled ON while waiting at this SAME prompt (via pause menu), the timer starts immediately.
    - If timers_on is toggled OFF mid-prompt, the timer stops immediately.
    - Timer truly freezes while pause menu is open.
    """
    global pause_enabled, in_pause_menu, timers_on
    global animation_on, level
    global last_ext_prefix_time, last_scroll_time, last_scroll_redraw_time
    global last_pulse_time, pulse_elapsed_marks, pulse_marks

    buffer = ""

    sys.stdout.write("\x1b[0m")
    sys.stdout.flush()

    print(prompt, end="", flush=True)

    # Create a dedicated STATUS LINE directly below the input line (once).
    _reserve_status_line_below_input()

    # Only ever rewrite the LAST line (usually "> ")
    prompt_last_line = prompt.split("\n")[-1]

    # Timer state (can be toggled live)
    timer_running = bool(timers_on)
    start = time.time() if timer_running else None
    paused_total = 0.0
    last_whole = int(timeout_seconds) if timer_running else None

    # --- Level emote pulses (deterministic plan; always defined) ---
    # NOTE: must exist even if timers_on is already True when we enter this prompt,
    # otherwise the pulse block will reference undefined locals.
    pulses_fired = set()
    pulse_elapsed_marks = []
    if timer_running and animation_on and level in ("one", "two"):
        # Two pulses: at 30% and 60% elapsed (== 70% and 40% remaining)
        pulse_elapsed_marks = [timeout_seconds * 0.30, timeout_seconds * 0.60]


    # Initial render (shows pause hint even if timer is OFF)
    _timed_line_render(prompt_last_line, buffer, last_whole)

    # -------- Windows --------
    if platform.system() == "Windows":
        _flush_pending_input_windows()  # prevent àPàH junk from prior scroll events

        awaiting_ext_code = False  # follow-up byte after \x00/\xe0 (prevents UnboundLocalError)

        last_ext_prefix_time = 0.0   # when we last saw \x00/\xe0
        last_scroll_time = 0.0       # when we last handled H/P as scroll
        last_pulse_time = 0.0        # cooldown so pulses feel intentional
        last_scroll_redraw_time = 0.0  # throttle redraws to reduce flicker

        while True:
            bg_update()
            time.sleep(0.02)

            if timers_on and not timer_running:
                timer_running = True
                start = time.time()
                paused_total = 0.0
                last_whole = int(timeout_seconds)

                # Re-arm pulses IMMEDIATELY when timers come back online mid-prompt
                pulses_fired = set()
                if animation_on and level in ("one", "two"):
                    pulse_elapsed_marks = [timeout_seconds * 0.30, timeout_seconds * 0.60]
                else:
                    pulse_elapsed_marks = []


                _timed_line_render(prompt_last_line, buffer, last_whole)

            if (not timers_on) and timer_running:
                timer_running = False
                start = None
                paused_total = 0.0
                last_whole = None

                # Reset pulse plan when timer is not running
                pulses_fired = set()
                pulse_elapsed_marks = []

                _timed_line_render(prompt_last_line, buffer, last_whole)

            # Countdown (only if timer is currently running)
            if timer_running:
                elapsed = time.time() - start - paused_total
                remaining = timeout_seconds - elapsed

                new_whole = max(0, int(remaining + 0.999))  # ceil-ish, feels nicer
                if new_whole != last_whole:
                    last_whole = new_whole
                    _timed_line_render(prompt_last_line, buffer, last_whole)

                    # -------------------------
                    # Level emotes (two pulses per timed choice prompt)
                    # -------------------------
                    if animation_on and level in ("one", "two") and last_whole is not None and last_whole > 0:
                        if timer_running and start is not None:
                            # elapsed excludes paused_total already (you compute it above)
                            for mark in pulse_elapsed_marks:
                                if (mark not in pulses_fired) and (elapsed >= mark) and (remaining > 0):
                                    pulses_fired.add(mark)

                                    if level == "one":
                                        _anger_pulse_choices_redraw(prompt, prompt_last_line, buffer, last_whole)
                                    elif level == "two":
                                        _fear_shiver_choices_redraw(prompt, prompt_last_line, buffer, last_whole)

                if remaining <= 0:
                    # pressure / failure SFX (randomized)
                    play_timer_zero_sfx()

                    # Show a player-style input line BEFORE we clear the timer UI
                    if sys.stdout.isatty():
                        # TTY path (best-effort ANSI): rewrite input line + clear status line
                        sys.stdout.write("\r\x1b[2K" + f"{prompt_last_line}(ran out of time)")
                        sys.stdout.write("\n\x1b[2K")
                        sys.stdout.write("\r\n")
                        sys.stdout.flush()
                    else:
                        # Non-tty fallback
                        print(f"{prompt_last_line}(ran out of time)")

                    return "__TIMEOUT__"

            if msvcrt.kbhit():
                ch = msvcrt.getwch()

                # follow-up byte after \x00/\xe0
                if awaiting_ext_code:
                    awaiting_ext_code = False

                    # Only allow scroll + redraw during ACTIVE gameplay prompts.
                    # (Never inside pause_menu; never in menus; never when pause is disabled)
                    if game_state == "running" and pause_enabled and (not in_pause_menu):
                        if ch in ("H", "P"):
                            if ch == "H":
                                changed = scroll_story(+3)
                            else:  # "P"
                                changed = scroll_story(-3)

                            last_scroll_time = time.time()

                            # Drain any extra bytes left by the terminal scroll sequence.
                            _flush_pending_input_windows()

                            # If nothing actually moved (already at top/bottom), don't redraw (avoids flicker).
                            if not changed:
                                continue

                            # Throttle rapid wheel events to reduce flicker.
                            now_redraw = time.time()
                            if now_redraw - last_scroll_redraw_time < 0.12:
                                continue
                            last_scroll_redraw_time = now_redraw

                            wipe_visible_soft()

                            if level == "one":
                                title_banner()

                            redraw_story()

                            sys.stdout.write("\x1b[0m")
                            sys.stdout.flush()

                            sys.stdout.write(prompt_last_line)
                            sys.stdout.flush()

                            _reserve_status_line_below_input()

                            _timed_line_render(prompt_last_line, buffer, last_whole)

                    # ALWAYS swallow the follow-up byte
                    continue

                # If the terminal scrollwheel leaves a stray printable 'H'/'P' behind (sometimes without the
                # leading extended-code prefix), treat it as scroll so we never print ghost letters.
                if ch in ("H", "P") and game_state == "running" and pause_enabled and (not in_pause_menu):
                    if buffer == "":
                        if ch == "H":
                            changed = scroll_story(+3)
                        else:  # "P"
                            changed = scroll_story(-3)

                        last_scroll_time = time.time()

                        # Drain any extra bytes left by the terminal scroll sequence.
                        _flush_pending_input_windows()

                        # If nothing actually moved (already at top/bottom), don't redraw (avoids flicker).
                        if not changed:
                            continue

                        # Throttle rapid wheel events to reduce flicker.
                        now_redraw = time.time()
                        if now_redraw - last_scroll_redraw_time < 0.12:
                            continue
                        last_scroll_redraw_time = now_redraw

                        wipe_visible_soft()

                        if level == "one":
                            title_banner()

                        redraw_story()

                        sys.stdout.write("\x1b[0m")
                        sys.stdout.flush()

                        sys.stdout.write(prompt_last_line)
                        sys.stdout.flush()

                        _reserve_status_line_below_input()

                        _timed_line_render(prompt_last_line, buffer, last_whole)
                        continue

                # SPACE = pause (only during gameplay)
                if ch == " " and pause_enabled and not in_pause_menu:
                    # Measure exactly how long we were in the pause menu, so the timer truly freezes.
                    t0 = time.time()
                    pause_menu()  # returns when player chooses Continue
                    t1 = time.time()

                    if timer_running:
                        paused_total += (t1 - t0)

                    # redraw story + reprint prompt + redraw input line
                    # Strong wipe not needed; keep it lighter to reduce flicker.
                    wipe_visible_soft()
                    redraw_story()

                    # DO NOT re-print full prompt (duplicates choice block and breaks glyph overwrite).
                    sys.stdout.write(prompt_last_line)
                    sys.stdout.flush()

                    _reserve_status_line_below_input()

                    _timed_line_render(prompt_last_line, buffer, last_whole)
                    continue

                # Enter
                if ch in ("\r", "\n"):
                    entered = buffer.strip()

                    # Lock the final input onto the SAME input line the timer UI was rendering,
                    # then clear the status line, then move to a fresh line for story output.
                    if sys.stdout.isatty():
                        sys.stdout.write("\x1b[0m")  # force white
                        sys.stdout.write("\r\x1b[2K" + f"{prompt_last_line}{entered}")  # replace input line
                        sys.stdout.write("\n\x1b[2K")  # clear status line
                        sys.stdout.write("\r\n")       # new line for upcoming story prints
                        sys.stdout.flush()
                    else:
                        # Non-tty fallback: just print once.
                        sys.stdout.write("\x1b[0m")
                        sys.stdout.flush()
                        print(f"{prompt_last_line}{entered}")

                    log_player_input(entered)
                    return entered

                # Backspace
                if ch == "\b":
                    if buffer:
                        buffer = buffer[:-1]
                    _timed_line_render(prompt_last_line, buffer, last_whole)
                    continue
                
                # extended key prefix
                if ch in ("\x00", "\xe0"):
                    awaiting_ext_code = True
                    last_ext_prefix_time = time.time()
                    continue

                # ESC -> eat ANSI sequence
                if ch == "\x1b":
                    _eat_ansi_escape_windows()
                    continue

                # Ignore other non-printable control chars
                if ord(ch) < 32:
                    continue

                # If the terminal leaked a stray scroll code ('H'/'P') without the prefix byte,
                # swallow it briefly after scroll-related activity (prevents ghost letters).
                now = time.time()
                if ch in ("H", "P") and (now - last_ext_prefix_time < 1.00 or now - last_scroll_time < 1.00):
                    continue

                # Normal character
                buffer += ch
                _timed_line_render(prompt_last_line, buffer, last_whole)

    # -------- macOS/Linux --------
    else:
        # Best-effort: poll stdin so we can keep updating timer/pause hint.
        while True:
            bg_update()
            time.sleep(0.02)

            if timers_on and not timer_running:
                timer_running = True
                start = time.time()
                paused_total = 0.0
                last_whole = int(timeout_seconds)

                # Plan EXACTLY two pulse moments in "seconds remaining"
                pulses_fired = set()
                if animation_on and level == "one":
                    m1 = max(1, int(round(timeout_seconds * 0.70)))
                    m2 = max(1, int(round(timeout_seconds * 0.40)))
                    pulse_marks = [m for m in sorted(set([m1, m2]), reverse=True) if 0 < m < timeout_seconds]
                else:
                    pulse_marks = []

                _timed_line_render(prompt_last_line, buffer, last_whole)

            if (not timers_on) and timer_running:
                timer_running = False
                start = None
                paused_total = 0.0
                last_whole = None

                # Reset pulse plan when timer is not running
                pulses_fired = set()
                pulse_marks = []

                _timed_line_render(prompt_last_line, buffer, last_whole)

            if timer_running:
                elapsed = time.time() - start - paused_total
                remaining = timeout_seconds - elapsed

                new_whole = max(0, int(remaining + 0.999))
                if new_whole != last_whole:
                    last_whole = new_whole
                    _timed_line_render(prompt_last_line, buffer, last_whole)

                if remaining <= 0:
                    # pressure / failure SFX (randomized)
                    play_timer_zero_sfx()

                    if sys.stdout.isatty():
                        sys.stdout.write("\r\x1b[2K" + f"{prompt_last_line}(ran out of time)")
                        sys.stdout.write("\n\x1b[2K")
                        sys.stdout.write("\r\n")
                        sys.stdout.flush()
                    else:
                        print(f"{prompt_last_line}(ran out of time)")
                    return "__TIMEOUT__"

            rlist, _, _ = select.select([sys.stdin], [], [], 0)
            if rlist:
                _timed_line_clear()
                line = sys.stdin.readline()
                play_enter_sfx()
                return line.strip()



        
def pause_menu():
    """
    Pause menu:
    1) Continue (resume gameplay)
    2) Language toggle (placeholder)
    3) Music ON/OFF (BG only; does NOT affect wolf loop or enter SFX)
    4) Timers ON/OFF (placeholder)
    5) Animation ON/OFF (placeholder)
    """
    global language, music_on, timers_on, animation_on
    global current_bg_key, pending_loop_key
    global in_pause_menu, pause_enabled

    prev_pause_enabled = pause_enabled
    in_pause_menu = True
    pause_enabled = False  # disable SPACE while pause menu is open

    try:
        # remember what was playing
        resume_bg_key = desired_bg_key
        resume_pending = desired_pending_key
        
        # stop BG music, start wolf ambience (separate channel)
        bg_stop()
        pause_wolf_start()

        while True:
            # - scrollback=True is a best-effort attempt to keep the pause screen out of terminal history
            # - push_lines=False prevents the "newline push" from polluting scrollback
            screen_reset(scrollback=True, push_lines=False)
            print("\n\n=== PAUSED ===\n")  # plain print (NOT print_pause)

            music_label  = "ON" if music_on else "OFF"
            timers_label = "ON" if timers_on else "OFF"
            anim_label   = "ON" if animation_on else "OFF"
            lang_label   = "English" if language == "EN" else "Português (BR)"

            choice = input_with_audio(
                "1. Continue\n"
                f"2. Language: {lang_label}\n"
                f"3. Music: {music_label}\n"
                f"4. Timers: {timers_label}\n"
                f"5. Animation: {anim_label}\n"
                "> "
            ).strip()

            if choice == "1":
                pause_wolf_stop()

                if music_on:
                    if resume_pending and resume_bg_key:
                        bg_intro_then_loop(resume_bg_key, resume_pending)
                    elif resume_bg_key:
                        bg_play(resume_bg_key, loop=True)
                    else:
                        # fallback: pick based on where we are
                        track = active_gameplay_track
                        bg_play(track, loop=True)

                return  # EXIT pause menu

            elif choice == "2":
                language = "PT" if language == "EN" else "EN"
                new_lang_label = "English" if language == "EN" else "Português (BR)"
                print(f"\nLanguage set to {new_lang_label}.\n")
                time.sleep(1.0)

            elif choice == "3":
                if music_on:
                    music_disable()
                else:
                    music_enable()
                    if resume_pending and resume_bg_key:
                        bg_intro_then_loop(resume_bg_key, resume_pending)
                    elif resume_bg_key:
                        bg_play(resume_bg_key, loop=True)
                    else:
                        track = active_gameplay_track
                        bg_play(track, loop=True)
                print(f"\nMusic turned {'ON' if music_on else 'OFF'}.\n")
                time.sleep(1.5)

            elif choice == "4":
                timers_on = not timers_on
                print(f"\nTimers turned {'ON' if timers_on else 'OFF'}.\n")
                time.sleep(1.5)

            elif choice == "5":
                animation_on = not animation_on
                print(f"\nAnimation turned {'ON' if animation_on else 'OFF'}.\n")
                time.sleep(1.5)

            else:
                print("\nPlease choose 1–5.\n")
                time.sleep(1.5)

    finally:
        pause_wolf_stop()
        in_pause_menu = False
        pause_enabled = prev_pause_enabled

# -------------------------
# Legacy clear_screen (kept for now)
# -------------------------

def clear_screen(delay=0, clear_scrollback=False):
    """
    Legacy clear helper (best-effort).
    Clears the visible screen. If clear_scrollback=True, attempts to clear scrollback too.
    """
    # NOTE: VS Code terminal + Git Bash can ignore parts of 'cls' / scrollback clearing,
    # so this uses ANSI escapes when possible, with OS-command fallback.
    # Preferred modern tools: screen_reset() / force_hard_clear() / enter_alt_screen() / wipe_visible().
    time.sleep(delay)

    # Try ANSI first (works in most modern terminals when isatty is True)
    if sys.stdout.isatty():
        if clear_scrollback:
            # Clear screen + home + clear scrollback
            sys.stdout.write("\x1b[2J\x1b[H\x1b[3J")
        else:
            # Clear screen + home
            sys.stdout.write("\x1b[2J\x1b[H")
        sys.stdout.flush()
        return

    # Fallback to OS commands (still useful if ANSI isn't honored)
    if platform.system() == "Windows":
        # In Git Bash / MSYS terminals, "clear" is usually correct even on Windows.
        if os.environ.get("MSYSTEM") or os.environ.get("TERM"):
            os.system("clear")
        else:
            os.system("cls")
    else:
        os.system("clear")

def wait_for_enter_with_audio():
    """
    Wait for Enter while still calling bg_update() so audio can transition.
    More reliable than input(prompt) in some terminals where the prompt can be visually eaten.
    """
    if platform.system() == "Windows":
        while True:
            bg_update()
            time.sleep(0.02)
            if msvcrt.kbhit():
                ch = msvcrt.getwch()
                if ch in ("\r", "\n"):
                    return
    else:
        # Best-effort fallback (audio won't update while blocking).
        input()

def pause_continue():
    """
    Press-Enter gate used on transitions (game over, between levels, etc.).
    This version prints the prompt ourselves and then waits for Enter,
    because some terminals can visually 'eat' prompts that are printed from inside
    a timed/status-line redraw context.
    """
    global pause_enabled
    prev = pause_enabled
    pause_enabled = False  # disable pause + hide hint during this prompt

    if sys.stdout.isatty():
        # Clear any timed-input UI remnants so they can't overwrite this prompt.
        sys.stdout.write("\x1b[0m")
        try:
            _timed_line_clear()
        except Exception:
            pass
        try:
            clear_pause_hint()
        except Exception:
            pass

        # Move to a clean line and clear below.
        sys.stdout.write("\r\n\x1b[J")

        # Print the prompt in WHITE (not story-blue).
        sys.stdout.write(Back.BLACK + Fore.WHITE + "(Press Enter to continue...)\n> " + "\x1b[0m")
        sys.stdout.flush()

        try:
            wait_for_enter_with_audio()
        finally:
            pause_enabled = prev
        return

    # Non-tty fallback
    try:
        input("\n(Press Enter to continue...)\n> ")
    finally:
        pause_enabled = prev

# ============================================================
# CHAPTER 3 — Globals State & Constants
# ============================================================
# NOTE: Some runtime globals live near their systems for locality:
# - Audio runtime state (Chapter 1): music_on, current_bg_key, pending_loop_key,
#   desired_bg_key, desired_pending_key, active_gameplay_track
# - SFX runtime counter (Chapter 2): sfx_index

# [2.4.A] Core runtime state
# NOTE: refactor-only pass: do not rename these or change defaults.
game_state = "running" # "running", "game over", "game won", "paused", "quit"
level = "one"          # "one" or "two"
lives = 0              # will be set per level

language = "EN"
timers_on = True
animation_on = True
in_pause_menu = False  # True only while pause_menu is open
pause_enabled = False  # only True during gameplay (not main menu / not win/over screens)

character = None       # "soulmate" or "child"
character_name = ""    # name typed at start of game
player_name = ""       # for soulmate path
player_role = ""       # "Mommy" or "Daddy" for child path
missing_parent = ""    # the opposite of player_role
game_over_level = "one"

# Win tracking (used for bonus_scene routing)
won_characters = set()        # e.g., {"child", "soulmate"}
bonus_scene_context = None    # captured from the child path so soulmate can still trigger bonus_scene

# Terminal alt-screen tracking
_alt_screen = False # set to true when we use screen buffering


# [2.4.B] Timeout / idle responses
# For later mobile port; swap to "phone" when you want the 4th-wall lines to match.
DEVICE_TYPE = "computer"

IDLE_LINES = {
    "child": [
        "Are you paying attention to me?",
        "I'm hungry.",
        "Can I have a puppy?",
        f"Can I play on the {DEVICE_TYPE}?",
    ],
    "soulmate": [
        "You look distracted.",
        "Did you hear what I said?",
        f"Why are you on your {DEVICE_TYPE} while we're talking?",
        "Why are you so silent?",
    ],
}

# Each character gets a shuffled "bag". We pop from it so no repeats until empty.
_idle_bag = {"child": [], "soulmate": []}

def get_idle_character_response() -> str:
    """
    Returns a non-repeating idle response for the CURRENT character.
    No repeats until all 4 have been used, then it reshuffles.
    """
    global _idle_bag, character

    if character not in _idle_bag:
        _idle_bag[character] = []

    if not _idle_bag[character]:
        bag = IDLE_LINES[character].copy()
        random.shuffle(bag)
        _idle_bag[character] = bag

    return _idle_bag[character].pop()

def handle_choice_timeout():
    """
    Prints the universal timeout thought + a character-specific idle response.
    Called only when the moral-timer reaches 0.
    """
    # always appears
    print_pause("\n(Indecision is a decision)\n")

    line = get_idle_character_response()

    if character == "child":
        print_pause(f"\n{character_name} says, '{line}'\n")
    else:
        print_pause(f"\n{character_name} says, '{line}'\n")


# [2.4.C] Timer tuning
# FINAL (production pacing): likely ~10s once print_pause() delays are 2.0–3.0s.
# TEST (dev pacing): half speed for rapid iteration.
TIMER_SECONDS_FINAL = 10
TIMER_SECONDS_TEST  = 5

# Use TEST during development; switch to FINAL for production pacing.
TIMER_SECONDS = TIMER_SECONDS_TEST


# [2.4.D] Transcript configuration
STORY_LOG = []
MAX_LOG_LINES = 300

# 0 = bottom (latest). Higher = scrolled upward.
story_scroll_offset_lines = 0

# Title banner consumes 8 terminal rows (7 lines + a blank spacer).
TITLE_BANNER_HEIGHT = 8


def _story_view_capacity_lines() -> int:
    """
    How many transcript lines we can safely draw without causing the terminal to scroll.
    Reserve:
      - Input prompt line
      - Status/timer line
      - Title banner height during Level 1 gameplay
    """
    rows = shutil.get_terminal_size((80, 24)).lines

    reserved = 2  # input prompt + status/timer line

    # Level 1 prints the big title banner above the story during gameplay.
    if game_state == "running" and level == "one":
        reserved += TITLE_BANNER_HEIGHT

    return max(5, rows - reserved)


def _flatten_story_log_to_lines() -> list[str]:
    """
    STORY_LOG stores 'chunks' (often with embedded newlines).
    Convert the entire log into a list of *visual* lines (each includes its '\n' if present).
    """
    text = "".join(STORY_LOG)
    lines = text.splitlines(True)  # keepends=True
    return lines

def _clamp_story_scroll():
    global story_scroll_offset_lines
    lines = _flatten_story_log_to_lines()
    cap = _story_view_capacity_lines()
    max_offset = max(0, len(lines) - cap)
    story_scroll_offset_lines = max(0, min(story_scroll_offset_lines, max_offset))

def ensure_blank_line_before_choices():
    """
    For both STORY_LOG (redraw_story) and immediate visible terminal output,
    ensure there is exactly one blank line before a choice block.
    Prevents choices from sticking to the previous story line
    when a trailing \\n was accidentally omitted.
    """
    if not STORY_LOG:
        return

    # Look at the last logged line
    last = STORY_LOG[-1]

    # If it's not already a blank line, add one
    if last.strip() != "":
        STORY_LOG.append("\n")

        # Keep log bounded
        if len(STORY_LOG) > MAX_LOG_LINES:
            STORY_LOG.pop(0)

        _clamp_story_scroll()

        # Print immediately with visible blank line before player input line
        sys.stdout.write(Back.BLACK + Fore.LIGHTBLUE_EX + "\n" + "\x1b[0m")
        sys.stdout.flush()

def print_choice_pair(option1: str, option2: str):
    ensure_blank_line_before_choices()  # this is the ONE source of blank line spacing
    print_pause(f"1. {option1}")
    print_pause(f"2. {option2}")

def ask_choice_pair(option1: str, option2: str) -> str:
    """
    Untimed 1/2 choice pair that:
    - always has a blank line above it
    - always lands in STORY_LOG
    - returns the player's raw input (validated by caller if desired)
    """
    # NOTE: input_with_audio() applies pause_prompt() internally.
    print_choice_pair(option1, option2)
    return input_with_audio("> ").strip()  # RAW prompt


def ask_choice_pair_timed(option1: str, option2: str, seconds: int) -> str:
    """
    Timed moral choice pair.
    """
    # Important: DO NOT use pause_prompt() here because timed input already renders
    # the pause hint on the status line via _timed_line_render().
    print_choice_pair(option1, option2)

    # Do NOT extend the timer for glyph animation.
    # Pulses are now very short, so readability stays high.
    return input_with_audio_timeout("> ", timeout_seconds=seconds, default_choice="2").strip()

def scroll_story(delta_lines: int) -> bool:
    """
    delta_lines > 0 scrolls UP (older)
    delta_lines < 0 scrolls DOWN (newer)

    Returns True if the scroll offset actually changed (helps avoid needless redraw flicker).
    """
    global story_scroll_offset_lines
    before = story_scroll_offset_lines
    story_scroll_offset_lines += delta_lines
    _clamp_story_scroll()
    return story_scroll_offset_lines != before


def poll_pause_hotkey():
    """
    Non-blocking check: SPACE pauses.
    """
    # IMPORTANT: We swallow everything else so mouse-wheel/arrow/PgUp sequences
    # can NEVER leak into prompts or cause weird behavior during print_pause().
    global in_pause_menu, pause_enabled

    if (not pause_enabled) or in_pause_menu:
        return False

    if platform.system() != "Windows":
        return False

    # Use a tiny bit of state to swallow the follow-up byte after \x00/\xe0
    if not hasattr(poll_pause_hotkey, "_awaiting_ext_code"):
        poll_pause_hotkey._awaiting_ext_code = False  # type: ignore[attr-defined]

    if msvcrt.kbhit():
        ch = msvcrt.getwch()

        # If we previously saw an extended-prefix, swallow its follow-up code.
        if poll_pause_hotkey._awaiting_ext_code:  # type: ignore[attr-defined]
            poll_pause_hotkey._awaiting_ext_code = False  # type: ignore[attr-defined]
            return False

        if ch == " ":
            return True

        # Extended key prefix: swallow the next byte too.
        if ch in ("\x00", "\xe0"):
            poll_pause_hotkey._awaiting_ext_code = True  # type: ignore[attr-defined]
            return False

        # ANSI escape: eat the rest of it.
        if ch == "\x1b":
            _eat_ansi_escape_windows()
            return False

        # Swallow everything else (NO ungetwch)
        return False

    return False

# ============================================================
# CHAPTER 4 — Terminal UI Rendering & Transcript (Story Log)
# ============================================================

# [2.3.A] Transcript printing (prints + stores in STORY_LOG)

def print_pause(msg):
    global story_scroll_offset_lines

    # Normalize message formatting for BOTH:
    # 1) what we store (story log)
    # 2) what we print (visible transcript)
    #
    # Rules:
    # - collapse leading newlines to at most ONE (so "\nHello" is fine, "\n\nHello" isn't)
    # - ensure it ends with exactly ONE newline (so lines always break)
    # [Function: print_pause]

    text = msg

    # ---- leading spacing: allow at most one blank line before content ----
    if text.startswith("\n"):
        text = "\n" + text.lstrip("\n")

    # ---- trailing spacing: ensure exactly one newline ----
    text = text.rstrip("\n") + "\n"

    # Prevent long timed-choice option lines from wrapping.
    # Wrapping breaks the "choice block is exactly 2 lines above the prompt" assumption,
    # which is the root cause of the anger-glyph stacking/duplication glitch.
    if sys.stdout.isatty():
        stripped = text.lstrip("\n")
        if stripped.startswith("1. ") or stripped.startswith("2. "):
            cols = shutil.get_terminal_size((80, 24)).columns
            one_line = text.rstrip("\n")
            if cols and len(one_line) >= cols:
                one_line = one_line[: max(0, cols - 2)] + "…"
                text = one_line + "\n"

    # store for redraw (no color codes)
    STORY_LOG.append(text)
    if len(STORY_LOG) > MAX_LOG_LINES:
        STORY_LOG.pop(0)

    _clamp_story_scroll()

    # visible print (no implicit newline; our text already ends with '\n')
    sys.stdout.write(Back.BLACK + Fore.LIGHTBLUE_EX + text + "\x1b[0m")
    sys.stdout.flush()

    # Sleep in small chunks so SPACE can interrupt for pause
    total = 1.0
    step = 0.05
    elapsed = 0.0

    while elapsed < total:
        bg_update()

        if poll_pause_hotkey():
            screen_reset(scrollback=False, push_lines=False)
            pause_menu()
            screen_reset(scrollback=False, push_lines=False)

            # Level 1 should keep the title banner visible during gameplay.
            if game_state == "running" and level == "one":
                title_banner()

            redraw_story()

        time.sleep(step)
        elapsed += step

# [2.3.B] UI-only printing (prints only; does NOT store in STORY_LOG)

def print_ui(text: str, *, color: bool = True):
    """
    UI-only print:
    - preserves the text EXACTLY (including line breaks)
    - does NOT write to STORY_LOG (so redraw_story() will NOT bring it back later)
    - keeps styling consistent with game
    """
    if color:
        sys.stdout.write(Back.BLACK + Fore.LIGHTBLUE_EX + text + "\x1b[0m")
    else:
        sys.stdout.write(text)

    # Do not add extra newlines here—caller controls formatting
    sys.stdout.flush()

# [2.3.C] Transcript recording (write-only to STORY_LOG)

def log_player_input(text: str):
    """
    Record player-entered text into STORY_LOG so it appears in the internal scroll view.
    Never record pause-menu input.
    """
    if in_pause_menu:
        return

    text = text.strip()

    # Don't clutter the log with blank "press Enter" inputs
    if text == "":
        return

    STORY_LOG.append(f"> {text}\n")

    # Keep memory bounded
    if len(STORY_LOG) > MAX_LOG_LINES:
        STORY_LOG.pop(0)

    _clamp_story_scroll()

def log_timeout_input():
    """
    Record a player-friendly timeout marker in the story log.
    This represents the player failing to decide in time.
    """
    if in_pause_menu:
        return

    STORY_LOG.append("> (ran out of time)\n")

    if len(STORY_LOG) > MAX_LOG_LINES:
        STORY_LOG.pop(0)

    _clamp_story_scroll()

# [2.3.D] Transcript rendering (read STORY_LOG + repaint screen)

# Lines we log from prompt prefixes should stay WHITE on redraw (not story-blue)
PROMPT_LOG_MARKER = "<<PROMPT>> "


def _print_story_raw(chunk: str):
    """
    Print a raw chunk (may contain '\n') without adding extra newlines.

    Rules:
    - Narrative/story text stays baby blue
    - Player input lines ("> ...") stay white, even after redraw/pause
     - Prompt prefix lines (logged questions like "What's their name?") stay white
    """
    if chunk.startswith(PROMPT_LOG_MARKER):
        # Strip marker before display (marker is log-only)
        visible = chunk[len(PROMPT_LOG_MARKER):]
        sys.stdout.write(Back.BLACK + Fore.WHITE + visible + "\x1b[0m")

    elif chunk.startswith("> "):
        sys.stdout.write(Back.BLACK + Fore.WHITE + chunk + "\x1b[0m")

    else:
        sys.stdout.write(Back.BLACK + Fore.LIGHTBLUE_EX + chunk + "\x1b[0m")

    sys.stdout.flush()


def redraw_story():
    """
    Repaint the story view based on scroll offset.
    Offset is measured in *lines* from the bottom.
    """
    _clamp_story_scroll()

    lines = _flatten_story_log_to_lines()
    cap = _story_view_capacity_lines()

    end = len(lines) - story_scroll_offset_lines
    start = max(0, end - cap)
    view = lines[start:end]

    for line in view:
        _print_story_raw(line)

# [2.3.E] Transcript lifecycle helpers (clear/reset)

def reset_story_log():
    global story_scroll_offset_lines
    STORY_LOG.clear()
    story_scroll_offset_lines = 0

# [2.3.F] Branding UI (title, icon, credits visuals)

TITLE_BANNER_TEXT = (
    " __  __ _           _    ____                    \n"
    "|  \\/  (_)_ __   __| |  / ___|  ___  _ __   __ _ \n"
    "| |\\/| | | '_ \\ / _` |  \\___ \\ / _ \\| '_ \\ / _` |\n"
    "| |  | | | | | | (_| |   ___) | (_) | | | | (_| |\n"
    "|_|  |_|_|_| |_|\\__,_|  |____/ \\___/|_| |_|\\__, |\n"
    "                                           |___/ \n"
    "                MIND SONG\n"
)

def title_banner(store_in_log: bool = False):
    # Title is UI-only. Do NOT store it in STORY_LOG (prevents stacking / scrollback clutter).
    # NOTE: store_in_log is currently unused (legacy / compatibility placeholder).
    print(Back.BLACK + Fore.LIGHTBLUE_EX + TITLE_BANNER_TEXT)
    print()   # little breathing space


# ============================================================
# Main Menu Snow — animated foreground layer
# ============================================================

_MENU_SNOW_BAG = []  # refilled + shuffled as needed

def _menu_snow_next_mode() -> str:
    """
    Main menu snow is FIXED.
    Always use indie_dust_sunbeam (legacy "C").
    """
    return "indie_dust_sunbeam"


def _normalize_snow_mode(mode: str) -> str:
    """Accept either descriptive names or legacy codes and return 'A'/'B'/'C'."""
    mapping = {
        "classical_asterisk": "A",
        "diagonal_noir": "B",
        "indie_dust_sunbeam": "C",
        "A": "A",
        "B": "B",
        "C": "C",
    }
    return mapping.get(mode, "C")

def _snow_density(cols: int, rows: int) -> int:
    # Tuned for "subtle but alive" across typical terminal sizes
    area = max(1, cols * rows)
    return max(18, min(90, area // 140))

def _init_snowfield(mode: str, cols: int, rows: int):
    """
    Each flake is a dict:
      x,y  (float positions)
      vx,vy (float velocity)
      ch   (render char)
    """
    flakes = []
    n = _snow_density(cols, rows)

    for _ in range(n):
        x = random.uniform(0, max(1, cols - 1))
        y = random.uniform(0, max(1, rows - 1))

        # micro-variation so it's not hypnotic
        base_vy = random.uniform(0.12, 0.55)

        if mode == "A":
            vx = 0.0
            vy = base_vy
            ch = random.choice(["*", "*", ".", "·"])  # mostly *; some fine dust
        elif mode == "B":
            # diagonal drift (wind)
            drift = random.choice([-1, 1]) * random.uniform(0.06, 0.20)
            vx = drift
            vy = base_vy
            ch = random.choice(["\\", "*", ".", "·"])
        else:
            # "C" — sideways, dust-in-a-sunbeam vibe
            vx = random.choice([-1, 1]) * random.uniform(0.18, 0.60)
            vy = random.uniform(-0.03, 0.06)  # tiny vertical wobble only
            ch = random.choice(["/", "·", ".", "*"])

        flakes.append({"x": x, "y": y, "vx": vx, "vy": vy, "ch": ch})

    return flakes

def _step_snowfield(mode: str, flakes, cols: int, rows: int):
    """
    Updates in-place. Wrap behavior differs per mode.
    """
    for f in flakes:
        # micro jitter (subtle, non-metronomic)
        jx = random.uniform(-0.03, 0.03)
        jy = random.uniform(-0.02, 0.02)

        f["x"] += f["vx"] + jx
        f["y"] += f["vy"] + jy

        # Wrap rules
        if mode in ("A", "B"):
            # vertical wrap
            if f["y"] >= rows:
                f["y"] = 0.0
                f["x"] = random.uniform(0, max(1, cols - 1))
            elif f["y"] < 0:
                f["y"] = float(rows - 1)

            # horizontal wrap for drift
            if f["x"] >= cols:
                f["x"] = 0.0
            elif f["x"] < 0:
                f["x"] = float(cols - 1)

        else:
            # mode C: primarily horizontal wrap, with gentle vertical wrap too
            if f["x"] >= cols:
                f["x"] = 0.0
                f["y"] = random.uniform(0, max(1, rows - 1))
            elif f["x"] < 0:
                f["x"] = float(cols - 1)
                f["y"] = random.uniform(0, max(1, rows - 1))

            if f["y"] >= rows:
                f["y"] = 0.0
            elif f["y"] < 0:
                f["y"] = float(rows - 1)

def _compose_menu_base_lines(menu_music_on: bool, status_msg: str = "") -> list[str]:
    """
    Returns *plain* (no ANSI) lines that we will render + overlay snow on top of.

    Layout goals:
    - Always at least 1 blank line ABOVE the title
    - Title stays baby blue later (renderer decides colors)
    - Options + prompt are white later
    - Optional status message appears UNDER the options (not at bottom of screen)
    """
    # (1) One blank line above title logo
    lines = [""] + TITLE_BANNER_TEXT.splitlines()

    # breathing space after title
    lines.append("")

    # menu options
    lines.append("1. Start game")
    lines.append("2. Language")
    lines.append(f"3. Music: {'ON' if menu_music_on else 'OFF'}")

    # (3) Status / acknowledgement line lives HERE (not bottom row)
    if status_msg:
        lines.append("")  # small spacer
        lines.append(status_msg)

    lines.append("")  # spacer before prompt
    lines.append("> ")  # buffer appended later
    return lines


def _render_menu_with_snow(
    frame,
    cols,
    rows,
    title_lines,
    options_lines,
    status_msg,
    buffer,
    show_fake_cursor=True,
    menu_left_override=None,
):
    """
    Draws one animation frame + menu UI.

    Fixes:
    - Snow is always white (even in title area)
    - Snow renders IN FRONT of all text/art (cursor stays on top so player can see it)
    - Cursor/prompt is pulled up (less vertical gap)
    """

    # Hard reset styles + hide cursor (best-effort across terminals)
    sys.stdout.write("\x1b[0m\x1b[?25l\x1b[?12l\x1b[H")

    # -----------------------------
    # Compose "base" text lines (no snow yet)
    # -----------------------------
    base_lines = []
    base_lines.append("")  # top margin
    base_lines.extend(title_lines)
    base_lines.append("")
    base_lines.extend(options_lines)

    # Blank line between menu options and input line (fixes jam against "3. Music")
    base_lines.append("")

    # Prompt line (this is where the fake cursor lives)
    prompt_line = "> " + buffer
    base_lines.append(prompt_line)

    # Capture the prompt row NOW (because we append status lines after this)
    prompt_row = len(base_lines) - 1

    # One blank spacer line so status is the *second* line below the input line
    base_lines.append("")

    # Reserve a status line ALWAYS (prevents jump).
    STATUS_RESERVE = max(
        len("Language switching will be added later."),
        len("Music turned ON."),
        len("Music turned OFF."),
        len("Please type a number and then press Enter."),
        len("X replies, 'Y? I don't understand.'"),
        0,
    )

    if status_msg:
        base_lines.append(status_msg.ljust(STATUS_RESERVE))
    else:
        base_lines.append(" " * STATUS_RESERVE)

    # -----------------------------
    # Helper to strip ANSI (if any)
    # -----------------------------
    def _strip_ansi(s: str) -> str:
        out = []
        esc = False
        i = 0
        while i < len(s):
            ch = s[i]
            if not esc:
                if ch == "\x1b":
                    esc = True
                else:
                    out.append(ch)
            else:
                if ch.isalpha():
                    esc = False
            i += 1
        return "".join(out)

    # base_lines is:
    #   0: ""
    #   1..len(title_lines): title
    title_count = 1 + len(title_lines)  # includes the top blank line
    menu_start = title_count + 1        # skip the blank line after title

    # -----------------------------
    # Compute menu block left-pad ONCE (no jumping)
    #
    # IMPORTANT: block width is based ONLY on the stable menu area
    # (options + prompt). Status text is excluded so it can never
    # re-center the whole block when it changes.
    # -----------------------------
    menu_block_end = prompt_row + 1  # stop before spacer + status
    menu_visible = [_strip_ansi(ln) for ln in base_lines[menu_start:menu_block_end]]
    block_width = max((len(ln) for ln in menu_visible), default=0)

    centered_left = max(0, (cols - block_width) // 2)

    # If provided:
    # - negative values mean "offset from centered_left" (nudge)
    # - non-negative values mean "absolute column" (pin)
    if isinstance(menu_left_override, int):
        if menu_left_override < 0:
            block_left = centered_left + menu_left_override
        else:
            block_left = menu_left_override

        # clamp into screen
        block_left = max(0, min(cols - 1, block_left))
    else:
        block_left = centered_left

    # -----------------------------
    # Build grids:
    # - text_grid: what we will finally draw
    # - base_grid: only the base text (used to color the title art blue safely)
    # -----------------------------
    text_grid = [[" " for _ in range(cols)] for _ in range(rows)]
    base_grid = [[" " for _ in range(cols)] for _ in range(rows)]

    # -----------------------------
    # Place base text FIRST
    # -----------------------------
    for r in range(min(rows, len(base_lines))):
        line = base_lines[r]
        vis = _strip_ansi(line)

        # Title area: center per-line
        if r < menu_start:
            left_pad = max(0, (cols - len(vis)) // 2)
        else:
            # Menu area: left-align within the centered block
            left_pad = block_left

        if left_pad >= cols:
            continue

        line_out = vis[: max(0, cols - left_pad)]

        for i, ch in enumerate(line_out):
            c = left_pad + i
            if 0 <= c < cols:
                text_grid[r][c] = ch
                base_grid[r][c] = ch

    # -----------------------------
    # Overlay snow AFTER text so it falls IN FRONT of title/options
    # (snow glyph overwrites whatever was there)
    # -----------------------------
    for r in range(min(rows, len(frame))):
        snow_row = frame[r]
        for c in range(min(cols, len(snow_row))):
            if snow_row[c] != " ":
                text_grid[r][c] = snow_row[c]

    # -----------------------------
    # Fake cursor (on top of everything so it stays readable)
    # -----------------------------
    cursor_col = block_left + 2 + len(buffer)  # "> " is 2 chars

    if show_fake_cursor and 0 <= prompt_row < rows and 0 <= cursor_col < cols:
        text_grid[prompt_row][cursor_col] = "█"

    # -----------------------------
    # Draw with mixed coloring:
    # - Title ART characters stay baby blue
    # - Snow ALWAYS white
    # - Menu text white
    # -----------------------------
    out_lines = []
    for r in range(rows):
        row_out = []
        current_color = None

        for c in range(cols):
            ch = text_grid[r][c]
            base_ch = base_grid[r][c]

            # Title should be blue ONLY where the base title text is still present.
            # If snow overwrote it, it becomes white (snow always white).
            is_title_char = (r < menu_start) and (base_ch != " ") and (ch == base_ch)
            desired_color = Fore.LIGHTBLUE_EX if is_title_char else Fore.WHITE

            if desired_color != current_color:
                row_out.append(Back.BLACK + desired_color)
                current_color = desired_color

            row_out.append(ch)

        row_out.append("\x1b[0m")
        out_lines.append("".join(row_out))

    # Fallback: park the *real* cursor where it belongs (even if it ignores hide)
    park_r = max(1, min(rows, prompt_row + 1))
    park_c = max(1, min(cols, cursor_col + 1))

    # Single write prevents the cursor briefly appearing at top-left between writes
    frame = "".join([
    "\x1b[?25l\x1b[?12l",            # hide + disable blink (best effort)
    "\x1b[H",                        # home
    "\n".join(out_lines),            # full frame
    f"\x1b[{park_r};{park_c}H",      # park cursor at prompt location
    "\x1b[?25l\x1b[?12l",            # re-hide + re-disable blink
    ])

    sys.stdout.write(frame)
    sys.stdout.flush()


def _build_snow_system(cols: int, rows: int, variant: str):
    """
    Build snow state for A/B/C variants (or descriptive names).
    Returns a dict the animator can advance each frame.
    """
    variant = _normalize_snow_mode(variant)

    # Keep snow inside visible area
    safe_top = 0
    safe_bottom = max(1, rows - 1)

    # Density tuning (keep your "subtle but alive" feel)
    if variant == "A":
        count = max(12, cols // 6)     # classic down
        dx_range = (0.0, 0.0)
        dy_range = (0.20, 0.55)
        glyphs = ["*", "*", ".", "·"]

    elif variant == "B":
        base_count = max(10, cols // 7)  # diagonal drift
        count = int(round(base_count * 1.30))  # +30% density
        dx_range = (-0.28, -0.08)        # drift left
        dy_range = (0.20, 0.55)
        glyphs = ["\\", "\\", "*", ".", "·"]

    else:
        # "C" = sideways / dust-in-sunbeam (glide RIGHT)
        base_count = max(10, cols // 7)
        count = int(round(base_count * 1.30))  # +30% density
        dx_range = (0.20, 0.55)          # glide right
        dy_range = (-0.01, 0.08)         # tiny fall / wobble
        glyphs = [".", "·", "*", "/", "\\"]

    flakes = []
    for _ in range(count):
        x = random.uniform(0, max(1, cols - 1))
        y = random.uniform(safe_top, safe_bottom)

        vx = random.uniform(dx_range[0], dx_range[1])
        vy = random.uniform(dy_range[0], dy_range[1])

        flakes.append({
            "x": x,
            "y": y,
            "vx": vx,
            "vy": vy,
            "ch": random.choice(glyphs),
            # micro-variation so it doesn’t look metronomic
            "wobble": random.uniform(-0.08, 0.08),
        })

    return {
        "variant": variant,
        "flakes": flakes,
    }


def _advance_snow_and_make_frame(snow, cols: int, rows: int):
    """
    Advance snow by one tick and return a full-screen frame (list[str])
    consisting ONLY of spaces + snow glyphs.
    Your menu renderer overlays title/options on top of this.
    """
    variant = _normalize_snow_mode(snow.get("variant", "C"))
    flakes = snow.get("flakes", [])

    # Build blank frame
    frame = [[" " for _ in range(cols)] for _ in range(rows)]

    # Motion “feel” tuning per variant
    if variant == "A":
        wobble_strength = 0.10
    elif variant == "B":
        wobble_strength = 0.12
    else:
        wobble_strength = 0.15

    for f in flakes:
        # micro variation: tiny horizontal wobble
        f["x"] += f["vx"] + (f["wobble"] * wobble_strength)
        f["y"] += f["vy"]

        # Wrap / respawn rules
        if variant == "A":
            if f["y"] >= rows:
                f["y"] = 0
                f["x"] = random.uniform(0, cols - 1)
        elif variant == "B":
            if f["y"] >= rows:
                f["y"] = 0
                f["x"] = random.uniform(0, cols - 1)
            if f["x"] < 0:
                f["x"] = cols - 1
        else:
            if f["x"] >= cols:
                f["x"] = 0
                f["y"] = random.uniform(0, rows - 1)
            if f["y"] >= rows:
                f["y"] = 0

        # draw flake (rounded positions)
        xi = int(f["x"])
        yi = int(f["y"])
        if 0 <= yi < rows and 0 <= xi < cols:
            frame[yi][xi] = f["ch"]

    return ["".join(row) for row in frame]


def _menu_input_with_snow(
    mode_or_title_lines,
    options_lines=None,
    snow_variant="C",
    ):
    """
    Menu loop with snow animation + non-blocking input.

    Backward-compatible:
    - If called like: _menu_input_with_snow(mode) where mode is legacy "A"/"B"/"C"
      OR the descriptive names ("classical_asterisk", etc),
      then we auto-build title/options and keep the snow variant fixed.
    - If called like: _menu_input_with_snow(title_lines, options_lines, snow_variant)
      we behave like the original signature.
    """
    global music_on

    # -----------------------------
    # Allow calling with ONE arg: snow mode name / code
    # -----------------------------
    if isinstance(mode_or_title_lines, str) and options_lines is None:
        mode = mode_or_title_lines
        snow_variant = mode

        title_lines = TITLE_BANNER_TEXT.splitlines()

        # Keep option 3 width stable (ON  vs OFF)
        music_label = "ON " if music_on else "OFF"
        options_lines = [
            "1. Start game",
            "2. Language",
            f"3. Music: {music_label}",
        ]
    else:
        title_lines = mode_or_title_lines
        if options_lines is None:
            raise TypeError(
                "_menu_input_with_snow(): options_lines is required when not calling with a snow mode name/code."
            )

    cols, rows = shutil.get_terminal_size((80, 25))

    # Main menu alignment:
    # Do NOT override the left column.
    # Let _render_menu_with_snow() center the menu block naturally
    menu_left_override = None
    # Visual alignment tweak:
    # The ASCII title art is left-heavy, so we nudge the centered menu left
    # to align under the first 'n' in "Mind".
    MENU_VISUAL_NUDGE = -9   # ← adjust if needed (-3, -5, etc.)

    if menu_left_override is None:
        menu_left_override = MENU_VISUAL_NUDGE

    snow = _build_snow_system(cols, rows, snow_variant)

    buffer = ""
    status_msg = ""
    status_until = 0.0

    # Clear + hide cursor + disable blink (best effort)
    sys.stdout.write("\x1b[2J\x1b[H\x1b[0m\x1b[?25l\x1b[?12l")
    sys.stdout.flush()

    if platform.system() == "Windows":
        _win_set_cursor_visible(False)  # kills the ghost cursor on Windows
        _flush_pending_input_windows()

    # Calm fake-cursor blink (seconds)
    CURSOR_PERIOD = 0.75   # full cycle
    CURSOR_ON = 0.45       # visible portion of cycle

    while True:
        bg_update()
        time.sleep(0.05)  # snow speed stays readable

        if status_msg and time.time() > status_until:
            status_msg = ""

        frame = _advance_snow_and_make_frame(snow, cols, rows)

        t = time.time()
        show_cursor = (t % CURSOR_PERIOD) < CURSOR_ON

        _render_menu_with_snow(
            frame=frame,
            cols=cols,
            rows=rows,
            title_lines=title_lines,
            options_lines=options_lines,
            status_msg=status_msg,
            buffer=buffer,
            show_fake_cursor=show_cursor,
            menu_left_override=menu_left_override,
        )

        if platform.system() == "Windows":
            if msvcrt.kbhit():
                ch = msvcrt.getwch()

                # ENTER = "submit"
                if ch in ("\r", "\n"):
                    cmd = buffer.strip()
                    buffer = ""
                    play_enter_sfx()

                    if cmd == "1":
                        # restore normal cursor before leaving menu
                        if platform.system() == "Windows":
                            _win_set_cursor_visible(True)
                        sys.stdout.write("\x1b[?25h\x1b[?12h\x1b[0m")
                        sys.stdout.flush()
                        return "1"

                    if cmd == "2":
                        status_msg = "Language switching will be added later."
                        status_until = time.time() + 1.2
                        continue

                    if cmd == "3":
                        if music_on:
                            music_disable()
                        else:
                            music_enable()
                            bg_play("menu", loop=True)

                        # Update option text in-place (keeps layout stable)
                        music_label = "ON " if music_on else "OFF"
                        if len(options_lines) >= 3:
                            options_lines[2] = f"3. Music: {music_label}"

                        status_msg = f"Music turned {'ON' if music_on else 'OFF'}."
                        status_until = time.time() + 1.2
                        continue

                    status_msg = "Please type a number and then press Enter."
                    status_until = time.time() + 1.2
                    continue

                # BACKSPACE
                if ch == "\b":
                    buffer = buffer[:-1]
                    continue

                # swallow extended keys / arrows / etc
                if ch in ("\x00", "\xe0"):
                    if msvcrt.kbhit():
                        msvcrt.getwch()
                    continue

                # swallow ANSI escape sequences (mouse wheel / arrows in some terminals)
                if ch == "\x1b":
                    _eat_ansi_escape_windows()
                    continue

                # Only accept printable characters
                if ord(ch) < 32:
                    continue

                buffer += ch

        else:
            rlist, _, _ = select.select([sys.stdin], [], [], 0)
            if rlist:
                line = sys.stdin.readline()
                play_enter_sfx()
                sys.stdout.write("\x1b[?25h\x1b[?12h\x1b[0m")
                sys.stdout.flush()
                return line.strip()


def _choice_pair_input_with_snow(
    option1_text: str,
    option2_text: str,
    snow_variant: str,
    preface_lines=None,
    title_lines=None,
    menu_left_override=None,
    ):
    """
    Animated (snow) option screen that returns "1" or "2".

    - Uses the same centered renderer as the main menu.
    - Invalid input shows the in-world "I don't understand" line (NOT a mechanical tip).
    - Status text is drawn in a reserved line so nothing jumps sideways.
    """
    global character, character_name, player_name, player_role

    if preface_lines is None:
        preface_lines = []
    if title_lines is None:
        title_lines = TITLE_BANNER_TEXT.splitlines()

    # Build menu lines (no snow yet)
    options_lines = []
    for ln in preface_lines:
        if ln is not None and str(ln).strip() != "":
            options_lines.append(str(ln))

    options_lines.append(f"1. {option1_text}")
    options_lines.append(f"2. {option2_text}")

    cols, rows = shutil.get_terminal_size((80, 25))
    snow = _build_snow_system(cols, rows, snow_variant)

    buffer = ""
    status_msg = ""
    status_until = 0.0

    # Clear + hide cursor + disable blink (best effort)
    sys.stdout.write("\x1b[2J\x1b[H\x1b[0m\x1b[?25l\x1b[?12l")
    sys.stdout.flush()

    if platform.system() == "Windows":
        _win_set_cursor_visible(False)
        _flush_pending_input_windows()

    CURSOR_PERIOD = 0.75
    CURSOR_ON = 0.45

    while True:
        bg_update()
        time.sleep(0.05)

        if status_msg and time.time() > status_until:
            status_msg = ""

        frame = _advance_snow_and_make_frame(snow, cols, rows)

        t = time.time()
        show_cursor = (t % CURSOR_PERIOD) < CURSOR_ON

        _render_menu_with_snow(
            frame=frame,
            cols=cols,
            rows=rows,
            title_lines=title_lines,
            options_lines=options_lines,
            status_msg=status_msg,
            buffer=buffer,
            show_fake_cursor=show_cursor,
            menu_left_override=menu_left_override,
        )

        if platform.system() == "Windows":
            if msvcrt.kbhit():
                ch = msvcrt.getwch()

                if ch in ("\r", "\n"):
                    cmd = buffer.strip()
                    buffer = ""
                    play_enter_sfx()

                    if cmd in ("1", "2"):
                        # restore normal cursor before leaving
                        if platform.system() == "Windows":
                            _win_set_cursor_visible(True)
                        sys.stdout.write("\x1b[?25h\x1b[?12h\x1b[0m")
                        sys.stdout.flush()
                        return cmd

                    # Invalid => in-world correction (matches valid_input())
                    if character == "child":
                        status_msg = f"{character_name} replies, '{player_role}? I don't understand.'"
                    else:
                        status_msg = f"{character_name} replies, '{player_name}? I don't understand.'"
                    status_until = time.time() + 1.2
                    continue

                if ch == "\x08":  # backspace
                    buffer = buffer[:-1]
                elif ch == "\x1b":  # ESC sequences
                    _eat_ansi_escape_windows()
                elif ch.isprintable():
                    buffer += ch

        else:
            rlist, _, _ = select.select([sys.stdin], [], [], 0)
            if rlist:
                line = sys.stdin.readline()
                play_enter_sfx()
                cmd = line.strip()

                if cmd in ("1", "2"):
                    sys.stdout.write("\x1b[?25h\x1b[?12h\x1b[0m")
                    sys.stdout.flush()
                    return cmd

                if character == "child":
                    status_msg = f"{character_name} replies, '{player_role}? I don't understand.'"
                else:
                    status_msg = f"{character_name} replies, '{player_name}? I don't understand.'"
                status_until = time.time() + 1.2
                continue


def _choice_input_with_snow(
    title_lines,
    options_lines,
    snow_variant="C",
    valid_cmds=("1", "2"),
    ):
    """
    Like _menu_input_with_snow(), but generic:
    - shows snow + title + options
    - accepts typed input
    - returns when the user submits a command in valid_cmds (default: "1" or "2")
    """

    cols, rows = shutil.get_terminal_size((80, 25))
    snow = _build_snow_system(cols, rows, snow_variant)

    buffer = ""
    status_msg = ""
    status_until = 0.0

    # Clear + hide cursor + disable blink (best effort)
    sys.stdout.write("\x1b[2J\x1b[H\x1b[0m\x1b[?25l\x1b[?12l")
    sys.stdout.flush()

    if platform.system() == "Windows":
        _win_set_cursor_visible(False)
        _flush_pending_input_windows()

    # Calm fake-cursor blink (seconds)
    CURSOR_PERIOD = 0.75
    CURSOR_ON = 0.45

    while True:
        bg_update()
        time.sleep(0.05)

        if status_msg and time.time() > status_until:
            status_msg = ""

        frame = _advance_snow_and_make_frame(snow, cols, rows)

        t = time.time()
        show_cursor = (t % CURSOR_PERIOD) < CURSOR_ON

        _render_menu_with_snow(
            frame=frame,
            cols=cols,
            rows=rows,
            title_lines=title_lines,
            options_lines=options_lines,
            status_msg=status_msg,
            buffer=buffer,
            show_fake_cursor=show_cursor,
        )

        # ----------------------------
        # Windows input (msvcrt)
        # ----------------------------
        if platform.system() == "Windows":
            if msvcrt.kbhit():
                ch = msvcrt.getwch()

                # ENTER = submit
                if ch in ("\r", "\n"):
                    cmd = buffer.strip()
                    buffer = ""
                    play_enter_sfx()

                    if cmd in valid_cmds:
                        _win_set_cursor_visible(True)
                        sys.stdout.write("\x1b[?25h\x1b[?12h\x1b[0m")
                        sys.stdout.flush()
                        return cmd

                    if character == "child":
                        status_msg = f"{character_name} replies, '{player_role}? I don't understand.'"
                    else:
                        status_msg = f"{character_name} replies, '{player_name}? I don't understand.'"
                    status_until = time.time() + 1.2
                    continue

                # BACKSPACE
                if ch == "\b":
                    buffer = buffer[:-1]
                    continue

                # swallow extended keys / arrows
                if ch in ("\x00", "\xe0"):
                    if msvcrt.kbhit():
                        msvcrt.getwch()
                    continue

                # swallow ANSI escape sequences
                if ch == "\x1b":
                    _eat_ansi_escape_windows()
                    continue

                # Only accept printable
                if ord(ch) < 32:
                    continue

                buffer += ch

        # ----------------------------
        # Non-Windows input (select)
        # ----------------------------
        else:
            rlist, _, _ = select.select([sys.stdin], [], [], 0)
            if rlist:
                line = sys.stdin.readline()
                play_enter_sfx()
                cmd = line.strip()

                if cmd in valid_cmds:
                    sys.stdout.write("\x1b[?25h\x1b[?12h\x1b[0m")
                    sys.stdout.flush()
                    return cmd

                if character == "child":
                    status_msg = f"{character_name} replies, '{player_role}? I don't understand.'"
                else:
                    status_msg = f"{character_name} replies, '{player_name}? I don't understand.'"
                status_until = time.time() + 1.2


def main_menu():
    global music_on, language
    global pause_enabled, game_state

    pause_enabled = False
    game_state = "menu"   # Prevents in-menu scroll redraw behavior

    # Always run the menu inside the alt screen so NOTHING can remain "above" it.
    enter_alt_screen()

    # One-time setup for this menu entry (no rerolls on input)
    wipe_visible()     # clears the alt screen buffer once
    reset_story_log()  # menu should start clean every time

    bg_play("menu", loop=True)  # sets desired_bg_key even if music is OFF

    # Bag draw ONCE per menu entry (fixes "reroll after each submit")
    mode = _menu_snow_next_mode()

    # Animated input handles 2/3/invalid internally now.
    _ = _menu_input_with_snow(mode)  # returns only when player chooses "1"

    # Start game
    bg_stop()
    game_state = "running"

    # Restore a normal screen state for gameplay
    screen_reset(scrollback=True, push_lines=False)
    new_game()
    return


# [2.3.G] Branding icon helpers

def _pad_block_right(lines: list[str]) -> list[str]:
    """
    IMPORTANT:
    When we center line-by-line, different line lengths cause different left-padding.
    That makes diagonals (like the flight path + mountains) look jagged.
    So we right-pad every line to the same width BEFORE centering.
    """
    if not lines:
        return lines
    width = max(len(s) for s in lines)
    return [s.ljust(width) for s in lines]

ICON_ART = (
    "        ✈\n"
    "         \\\n"
    "          \\\n"
    "           \\\n"
    "       /\\      /\\\n"
    "      /  \\    /  \\\n"
    "     /    \\  /    \\\n"
    "    /      \\/      \\\n"
    "\n"
)

def print_icon(color: str = Fore.LIGHTBLUE_EX):
    """Print the airplane icon in a specific color (UI-only)."""
    sys.stdout.write(Back.BLACK + color + ICON_ART + "\x1b[0m")
    sys.stdout.flush()


def name_character():
    global character_name
    character_name = input_with_audio("What's their name?\n> ")  # RAW prompt
    return character_name

def name_player():
    global player_name
    player_name = input_with_audio("Tell them your name to try to wake them\n> ")  # RAW prompt
    return player_name

# [2.3.H] Pause hint (cursor-save UI trick)

def show_pause_hint_under_input():
    """
    Renders '(Press SPACE to pause)' TWO lines below the current cursor:
      - one blank line
      - then the hint
    Cursor stays where the player is typing (on the prompt line).
    """
    if not (pause_enabled and not in_pause_menu):
        return

    hint = "(Press SPACE to pause)"

    # If not interactive, don't do cursor tricks.
    if not sys.stdout.isatty():
        return

    SAVE = "\x1b[s"
    RESTORE = "\x1b[u"

    # IMPORTANT: We do NOT modify the prompt text at all.
    # We just draw the hint below wherever the cursor currently sits.
    sys.stdout.write(SAVE + "\n\n" + hint + RESTORE)
    sys.stdout.flush()


def clear_pause_hint():
    """
    Erases the pause hint line that show_pause_hint_under_input() draws
    two lines below the cursor.
    """
    global pause_enabled, in_pause_menu

    if not (pause_enabled and not in_pause_menu):
        return
    if not sys.stdout.isatty():
        return

    # We print the hint 2 lines below the prompt line (because show_pause_hint_under_input() writes "\n\n")
    SAVE = "\x1b[s"
    RESTORE = "\x1b[u"

    # Move down 2 lines, clear that whole line, restore cursor
    sys.stdout.write(SAVE + "\x1b[2B" + "\x1b[2K" + "\r" + RESTORE)
    sys.stdout.flush()

def valid_input(option1: str, option2: str):
    while True:
        response = ask_choice_pair(option1, option2)
        if response == "1" or response == "2":
            return response
        else:
            # Echo the player's invalid input (response) instead of empty role/name vars.
            print_pause(f"\n{character_name} replies, '{response}? I don't understand.'\n")


def valid_input_timed(option1: str, option2: str, seconds: int):
    """
    Timed version for MORAL choice pairs only.
    - Only used where option 1 = "good" and option 2 = "bad"
    - Returns "__TIMEOUT__" on timeout (caller applies consequences)
    """
    while True:
        response = ask_choice_pair_timed(option1, option2, seconds)

        # Timer hit 0 => return sentinel immediately (caller handles consequences)
        if response == "__TIMEOUT__":
            return "__TIMEOUT__"

        if response == "1" or response == "2":
            return response
        else:
            # If they typed junk, keep the stress on: don't reset the timer here.
            if character == "child":
                print_pause(f"\n{character_name} replies, '{player_role}? I don't understand.'\n")
            else:
                print_pause(f"\n{character_name} replies, '{player_name}? I don't understand.'\n")


# ============================================================
# CHAPTER 5 — Narrative Content (Levels) & Script Helpers
# ============================================================

# [5.A] Script helpers (used by multiple story paths)

def choose_parent():
    return valid_input(
        "Tell them, 'Mommy is here.'",
        "Tell them, 'Daddy is here.'",
    )
   
def random_character():
    global character
    character = random.choice(["soulmate", "child"])
  
def get_lives():
    global lives
    lives = random.choice([2, 3])
    return lives

def apply_choice_timeout_side_effects() -> None:
    """
    Timed-choice timeout: centralize the exact side-effects used by narrative loops.
    """
    log_timeout_input()
    handle_choice_timeout()

# [5.B] Soulmate path — Level 1

def soulmate_level_one(): 
    # level_one_gameplay.ogg continues to loop
    global game_state, lives, game_over_level, level
    
    print_pause(
        f"\n{character_name} says they won't see you for a long time "
        "because of a business trip tomorrow.\n"
    )

    get_lives()

    bad_choices = [
        "Ask why they didn't tell you sooner.",
        "Tell them they always leave you alone as punishment for something you once said.",
        "Tell them all the reasons why they're wrong."
    ]

    character_escalates = [
        f"\n{character_name} explains, 'I didn't want to ruin your Christmas again, so I asked for the overtime.'\n",
        f"\n{character_name} says, 'You're not listening. You don't make me feel safe.'\n"
    ]

    index = 0

    while lives > 0 and index < len(bad_choices):
        choice = valid_input_timed(
            "Put on the bracelet",
            bad_choices[index],
            TIMER_SECONDS
        )

        if choice == "__TIMEOUT__":
            apply_choice_timeout_side_effects()
            # treat as bad choice (costs a life) and proceed to escalation like normal

        if "1" in choice:
            print_pause("\nYour pulse softens at the touch of the cool metal on your wrist.\n")
            choice = valid_input(
                "Ask them how they feel about the trip.",
                "Ask them what will make the trip easier.",
            )
            if "1" in choice:
                print_pause(f"\n{character_name} answers, 'I might not meet my deadline. And it's long distance for us.'\n")
            else:
                print_pause(f"\n{character_name} answers, 'I could get a good data plan to have unlimited video calls with you.'\n")
            
            print_pause(
                f"{character_name} gives a sleepy smile "
                "and wants to have breakfast with you.\n"
            )

            level = "two"
            return
        
        lives -= 1
        if index < len(character_escalates):
            print_pause(character_escalates[index])
        index += 1

    if lives == 0:
        bg_stop()
        bg_play("lose", loop=True)
        print_pause(
            f"\n{character_name} leaves the apartment sobbing,\n"
            "'I can't keep playing this game with myself.'"
        )
        print_pause(
            "\nYou try to tell them that they forgot their bracelet,\n"
            "but the elevator doors already closed.\n"
        )
        game_state = "game over"
        game_over_level = level
        handle_game_over()


# [5.C] Soulmate path — Level 2
def story_print_bracelet_inscription():
    # Narrative helper: keep this exact inscription line consistent across scenes.
    print_pause("\nThe bracelet has an inscription on it: 'mind the song.'\n")

def soulmate_level_two():
    # level_one_gameplay.ogg stops
    # level_two_gameplay.ogg starts and loops
    global game_state, lives, game_over_level, level

    bg_stop()
    bg_play("level2", loop=True)

    print_pause("\nLater that morning...")
    print_pause(
        f"You almost spit out your cereal when {character_name} says, "
        "'Maybe we should end things.'\n"
    )

    get_lives()

    bad_choices = [
        "Ask them why they didn't say anything before you moved in with them.",
        "Ask them if they met someone else.",
        "Tell them you don't deserve this."
    ]

    character_escalates = [
        f"\n{character_name} says they forgot to think about what they wanted.\n",
        f"\n{character_name} says, 'I don't think it would make a difference.'\n"
    ]

    index = 0

    while lives > 0 and index < len(bad_choices):
        choice = valid_input_timed(
            "Look at the bracelet",
            bad_choices[index],
            TIMER_SECONDS
        )

        if choice == "__TIMEOUT__":
            apply_choice_timeout_side_effects()
            # treat as bad choice (costs a life) and proceed to escalation like normal

        if "1" in choice:
            story_print_bracelet_inscription()
            choice = valid_input(
                "Ask why they felt like they could not tell you this until now.",
                "Thank them for trusting you with their deepest thoughts.",
            )
            if "1" in choice:
                # level_two_gameplay.ogg stops
                # game_won.ogg starts and loops
                bg_stop()
                bg_play("win", loop=True)
                print_pause(
                    f"\n{character_name} replies, "
                    "'Sometimes I still get afraid,\n"
                    "of taking off my mask with you.'\n"
                )
            elif "2" in choice:
                # level_two_gameplay.ogg stops
                # game_won.ogg starts and loops
                bg_stop()
                bg_play("win", loop=True)
                print_pause(
                f"{character_name} taps you on the head. "
                "'I always sing my thoughts for you.'\n"
            )

            print_pause(
                f"{character_name} dries their tears and says, 'In the dream, you asked,'"
            )
            print_pause('"Have you ever thought about us adopting..."')
            print_pause("'A dog?' you interrupt.")
            print_pause(f"'No,' {character_name} says. 'I mean a child.'\n")

            game_state = "game won"
            handle_game_won()
            return

        
        lives -= 1
        if index < len(character_escalates):
            print_pause(character_escalates[index])

        index += 1

    if lives == 0:
        bg_stop()
        bg_play("lose", loop=True)
        print_pause(
            f"\n{character_name} says, "
            "'Your feelings are the only ones that ever mattered in this relationship.'"
        )
        print_pause("'It's like a game you just want to win, except now it's over.'\n")
        game_state = "game over"
        game_over_level = level
        handle_game_over()


# [5.D] Child path — Level 1

def child_level_one():
    # level_one_gameplay.ogg continues to loop
    global game_state, lives, game_over_level, level
    
    print_pause(
        f"\n{character_name} says they don't want to spend the night with you anymore "
        "because of the nightmares.\n"
    )

    get_lives()

    bad_choices = [
        "Tell them that nightmares are not real.",
        "Tell them they need to go back to sleeping with diapers.",
        "Tell them all the reasons why they're wrong."
    ]

    character_escalates = [
        f"\n{character_name} says, "
        "'If bad dreams aren't real, why did the monsters pee in our bed?'\n",
        f"\n{character_name} says it's your fault that {missing_parent} died on the plane.\n"
    ]

    index = 0

    while lives > 0 and index < len(bad_choices):
        choice = valid_input_timed(
            "Put on the bracelet",
            bad_choices[index],
            TIMER_SECONDS
        )

        if choice == "__TIMEOUT__":
            apply_choice_timeout_side_effects()
            # treat as bad choice (costs a life) and proceed to escalation like normal

        if "1" in choice:
            print_pause("\nYour pulse softens at the touch of the cool metal on your wrist.\n")
            choice = valid_input(
                "Ask them what they would do if their toy had a nightmare.",
                f"Ask them what {missing_parent} would do if they had a nightmare.",
            )
            if "1" in choice:
                print_pause(
                    f"\n{character_name} answers, 'I would tell him to dance it off, like a puppy shakes water.'\n"
                )
            elif "2" in choice:
                print_pause(
                    f"\n'{missing_parent} would tell me to sing how I feel in my mind.'\n"
                )

            level = "two"
            return

        lives -= 1
        if index < len(character_escalates):
            print_pause(character_escalates[index])
        index += 1

    if lives == 0:
        bg_stop()
        bg_play("lose", loop=True)
        print_pause(
            f"\n{character_name} screams, 'I don't want to be adopted by you anymore!'\n"
        )
        game_state = "game over"
        game_over_level = level
        handle_game_over()


# [5.E] Child path — Level 2

def child_level_two():
    # level_one_gameplay.ogg stops
    # level_two_gameplay.ogg starts and loops
    global game_state, lives, game_over_level, level
    
    bg_stop()
    bg_play("level2", loop=True)

    print_pause("\nLater that morning at an outdoor cafe...")
    print_pause(f"You make airplane noises as you fly a spoon of yogurt into {character_name}'s mouth.")
    print_pause("You pretend to not see your boss waving at you.")
    print_pause(
        f"{character_name} says, '{missing_parent} said it's not nice to say hello.'\n"
    )

    # Player gets 2–3 emotional strikes in this scene.
    # Sometimes the heartbreak happens earlier (feels unpredictable on purpose).    
    get_lives()

    bad_choices = [
        f"Tell {character_name} that we only speak to {missing_parent} on Sundays in church.",
        "Tell them people might say mean things at school.",
        f"Introduce your boss as the one who flew {missing_parent} to the North Pole on Christmas."
    ]

    character_escalates = [
        f"\n{character_name} asks why they can't talk to {missing_parent} at school.\n",
        "\nYour boss pauses and looks up at you for direction.\n"
    ]

    index = 0

    while lives > 0 and index < len(bad_choices):
        # index 0 → questioning about school
        # index 1 → boss + dog + "Are you Mommy's friend?"
        # index 2 → possible final heartbreak depending on remaining lives

        
        choice = valid_input_timed(
            "Look at the bracelet",
            bad_choices[index],
            TIMER_SECONDS
        )

        if choice == "__TIMEOUT__":
            apply_choice_timeout_side_effects()
            # treat as bad choice (costs a life) and proceed to escalation like normal

        if "1" in choice:
            # level_two_gameplay.ogg stops
            # game_won.ogg starts and loops
            bg_stop()
            bg_play("win", loop=True)
            story_print_bracelet_inscription()
            choice = valid_input(
                f"Ask {character_name} what {missing_parent} is trying to say now.",
                f"Ask {character_name} if they want to wear the bracelet that {missing_parent} made.",
            )
            
            print_pause(
                f"\n{character_name} nods and beckons for you to kneel down so they can "
                "lean in and whisper,\n"
                f"'{missing_parent} says they hope you forgive them for ruining Christmas.'\n"
            )
            
            game_state = "game won"
            handle_game_won()
            return

        lives -= 1
        if index < len(character_escalates) and index == 1:
            print_pause(f"\n{character_name} waves at your boss.")
            print_pause("He comes over with his dog.")
            print_pause(f"{character_name} asks, 'Are you {missing_parent}'s friend?'\n")
        elif index < len(character_escalates):
            print_pause(character_escalates[index])
        index += 1

    if lives == 0:
        bg_stop()
        bg_play("lose", loop=True)
        print_pause(
            f"\n{character_name} blinks through tears. 'I want a real {missing_parent}.'\n"
        )
        game_state = "game over"
        game_over_level = level
        handle_game_over()


# ============================================================
# CHAPTER 5 (continued) — Entry + Shared Option Prompts
# ============================================================
# These are story-first helpers that *lead into* gameplay and feed Chapter 6 controllers.
# They intentionally avoid screen-transition ownership (that stays in Chapter 6).
def intro():
    # Transition into Level 1 gameplay audio (key-based).
    # We stop any current background track, then start looping "level1".
    global player_role, missing_parent
    global active_gameplay_track
    active_gameplay_track = "level1"
    
    bg_stop()
    bg_play("level1", loop=True)

    print_pause(f"\nYour {character} is still asleep in bed.")
    print_pause("They look like they're having a nightmare.")
    print_pause("You say their name softly to not startle them.\n")
    
    name_character()

    print_pause(f"\n'{character_name}, it's just a bad dream.'")
    print_pause("They open their eyes and shout, 'It's gonna crash!'")
    print_pause("They look at you and say, 'You're the pilot, aren't you?!'")
    print_pause("You tell them you're here.")

    if character == "child":
        # Choose Mommy or Daddy and set missing_parent accordingly
        choice = choose_parent()
        if "1" in choice:
            player_role = "Mommy"
            missing_parent = "Daddy"
        else:
            player_role = "Daddy"
            missing_parent = "Mommy"

    else:
        name_player()


def entry_point():
    # NOTE: We intentionally do NOT force a screen clear here.
    # This is story continuity, not a screen-transition controller.
    if character == "child":
        print_pause(f"\nYou sing to them, 'It's okay, {character_name}.'")
        print_pause(f"'{player_role} is here.'")
    else:
        print_pause(f"\n'{character_name}, you're okay.'")
        print_pause(f"'There's no pilot. It's me, {player_name}.'")
        
    print_pause(
        f"\n{character_name} squints at you and looks at the bracelet hanging above the bed. "
        "Maybe one of you will wear it today."
    )

def switch_characters():
    global character
    if character == "child":
        character = "soulmate"
    else: character = "child"
    
def game_over_options():
    title_lines = TITLE_BANNER_TEXT.splitlines() + _pad_block_right(ICON_ART.splitlines())
    return _choice_pair_input_with_snow(
        option1_text=f"Try again with {character_name}.",
        option2_text="Choose a different character",
        snow_variant="diagonal_noir",
        title_lines=title_lines,
    )

# Game-won alignment:
# Negative = nudge left from centered. Positive = absolute column.
GAME_WON_MENU_VISUAL_NUDGE = -1   # tweak this to scoot left/right

def game_won_options():
    title_lines = TITLE_BANNER_TEXT.splitlines() + _pad_block_right(ICON_ART.splitlines())

    # If the player has won with BOTH characters, the win menu becomes:
    # 1) Play again
    # 2) Say goodbye   <-- ONLY path that may trigger the bonus scene
    if len(won_characters) == 2:
        return _choice_pair_input_with_snow(
            option1_text="Play again",
            option2_text="Say goodbye",
            snow_variant="classical_asterisk",
            title_lines=title_lines,
            menu_left_override=GAME_WON_MENU_VISUAL_NUDGE,
        )

    # Otherwise, keep the per-character win menus
    if character == "child":
        return _choice_pair_input_with_snow(
            option1_text="Choose a different character.",
            option2_text="Say goodbye",
            snow_variant="classical_asterisk",
            title_lines=title_lines,
            menu_left_override=GAME_WON_MENU_VISUAL_NUDGE,
        )

    # soulmate
    return _choice_pair_input_with_snow(
        option1_text="Yes",
        option2_text="No",
        snow_variant="classical_asterisk",
        preface_lines=["Choose a different character?"],
        title_lines=title_lines,
        menu_left_override=GAME_WON_MENU_VISUAL_NUDGE,
    )


# ============================================================
# CHAPTER 6 — Core Flow / State Machine (Menus + Transitions)
# ============================================================

def _enter_clean_banner_screen():
    """
    Reset to a clean screen + fresh transcript + title banner.
    """
    screen_reset(scrollback=True, push_lines=False)
    reset_story_log()
    title_banner()

# [6.A] Win flow controller

def handle_game_won():
    # Win screen controller.
    # Primary design: the level triggers win music at the impact moment.
    # Safety net: this function starts win music only if it isn't already active/desired.
    global game_state, pause_enabled
    global current_bg_key, pending_loop_key, desired_bg_key
    global won_characters, bonus_scene_context

    pause_enabled = False

    if game_state == "game won":
        # Track which character(s) have won this run
        won_characters.add(character)

        # Capture child-only context so soulmate can still trigger the bonus scene later
        if character == "child":
            bonus_scene_context = {
                "character_name": character_name,
                "player_role": player_role,
                "missing_parent": missing_parent,
            }

        # Only start win music here if it isn't already the active/desired track.
        # (Primary design: level triggers win music at the impact moment.)
        if desired_bg_key != "win" and current_bg_key != "win":
            bg_play("win", loop=True)

        pause_continue()

        # Snow-rendered screen now owns the banner/icon. Keep transcript clean.
        reset_story_log()

        choice = game_won_options()
        reset_story_log()  # prevents redraw of win history in bonus scene and fresh attempt

        # ------------------------------------------------------------
        # RULE: Bonus scene triggers ONLY if BOTH characters have been won
        #       AND the player selects option 2 ("Say goodbye").
        # ------------------------------------------------------------
        if len(won_characters) == 2:
            if "1" in choice:
                restart()
                return
            elif "2" in choice:
                if bonus_scene_context:
                    bonus_scene(context=bonus_scene_context)
                quit()
                return

        # Otherwise: normal per-character behavior (NO bonus scene here)
        if "1" in choice:
            restart()
            return

        if "2" in choice:
            quit()
            return


# [5.F] Bonus scene controller (child-only)

def bonus_scene(context=None):
    global bn_character_name, bn_player_role, bn_missing_parent

    # Bonus scene music: play intro once, then loop the bonus track.
    # (Key-based: "bonus_intro" -> "bonus_loop")
    bg_stop()
    bg_intro_then_loop("bonus_intro", "bonus_loop")

    # Use captured child context if provided (so soulmate can still trigger this)
    ctx = context or {}
    bn_character_name = ctx.get("character_name", character_name)
    bn_player_role = ctx.get("player_role", player_role)
    bn_missing_parent = ctx.get("missing_parent", missing_parent)

    _enter_clean_banner_screen()

    # IMPORTANT: In the bonus scene, always use the captured CHILD context vars (bn_*),
    # never the current runtime globals (character_name/player_role/missing_parent),
    # because the soulmate path can trigger this scene.
    print_pause("\nBack home...")
    print_pause("You hang the bracelet up on the wall.")
    print_pause(f"In pajamas, {bn_character_name} looks at the airplane flying past the moon.")
    print_pause(f"'{bn_missing_parent} wants to know when we'll come find them.'")
    print_pause("'Uh-huh,' you say with a yawn.")
    print_pause(f"'You know, {bn_player_role}...'")
    print_pause("'Sweetheart,' you reply automatically as you close your eyes in bed.")
    print_pause(f"'Well, {bn_player_role}, they never found the plane.'")
    print_pause("Your eyes snap open. 'Who told you--'\n")
    pause_continue()


# [6.D] Game over flow controller

def handle_game_over():
    # Game-over screen controller.
    # Primary design: the level triggers lose music at the impact moment.
    # Safety net: this function starts lose music only if it isn't already active/desired.
    global game_state, pause_enabled
    global current_bg_key, pending_loop_key, desired_bg_key

    pause_enabled = False

    if game_state == "game over":
        # Only start lose music here if it isn't already the active/desired track.
        # (Primary design: level triggers lose music at the impact moment.)
        if desired_bg_key != "lose" and current_bg_key != "lose":
            bg_play("lose", loop=True)

        pause_continue()

        # Snow-driven game-over options screen (B = diagonal_noir)
        enter_alt_screen()
        wipe_visible()
        reset_story_log()

        title_lines = TITLE_BANNER_TEXT.splitlines() + _pad_block_right(ICON_ART.splitlines())
        options_lines = [
            f"1. Try again with {character_name}.",
            "2. Choose a different character",
        ]

        choice = _choice_input_with_snow(
            title_lines=title_lines,
            options_lines=options_lines,
            snow_variant="diagonal_noir",
            valid_cmds=("1", "2"),
        )

        reset_story_log()  # fresh attempt does not redraw game-over history

        if choice == "1":
            retry()
        elif choice == "2":
            restart()


# [6.B] Level progression + level transitions

def level_progression():
    global level, active_gameplay_track
    level = "one"
    active_gameplay_track = "level1"

    if character == "soulmate":
        soulmate_level_one()

        if game_state == "running" and level == "two":
            pause_continue()

            active_gameplay_track = "level2"

            enter_alt_screen()
            wipe_visible()
            reset_story_log()

            # DO NOT call title_banner() for level 2
            soulmate_level_two()

    else:
        child_level_one()

        if game_state == "running" and level == "two":
            pause_continue()

            active_gameplay_track = "level2"

            enter_alt_screen()
            wipe_visible()
            reset_story_log()

            # DO NOT call title_banner() for level 2
            child_level_two()


# [6.C] Run control (retry / restart / quit)

def retry():
    global game_state, pause_enabled, in_pause_menu
    global level, game_over_level, active_gameplay_track

    game_state = "running"
    pause_enabled = True
    in_pause_menu = False

    # Stop any currently playing background track before restarting gameplay audio.
    bg_stop()

    # lock retry to the level we actually died on
    level = game_over_level
    active_gameplay_track = "level2" if level == "two" else "level1"

    # fresh attempt shouldn't redraw previous attempt / game-over history
    enter_alt_screen()
    wipe_visible()
    reset_story_log()

    # Always set what SHOULD be playing.
    # bg_play() will only actually play if music_on is True.
    bg_play(active_gameplay_track, loop=True)
    
    # if retrying level 2, do NOT call level_progression()
    if level == "two":
        if character == "soulmate":
            soulmate_level_two()
        else:
            child_level_two()
    else:
        title_banner(store_in_log=True)
        entry_point()
        level_progression()
  
def restart():
    global game_state, pause_enabled
    game_state = "running"
    global active_gameplay_track
    active_gameplay_track = "level1"
    pause_enabled = True

    # stop any game-over loop that's still running
    bg_stop()

    # Always set what SHOULD be playing; bg_play only plays if music_on is True
    bg_play("level1", loop=True)
        
    switch_characters()

    enter_alt_screen()
    wipe_visible()   

    reset_story_log()
    title_banner(store_in_log=True)
    intro()
    entry_point()
    level_progression()

def quit():
    global game_state
    game_state = "quit"

    # We want a clean slate for credits.
    # Entering alt screen here is optional, but it keeps behavior consistent across terminals.
    enter_alt_screen()     # Keeps us in the clean gameplay buffer
    wipe_visible()         # Blank screen, no lingering above
    reset_story_log()      # Removes bonus scene text from memory

    title_banner()

    # Tiny “fade-in” beat for the whole credits block
    time.sleep(1.0)        # 1 second, feels cinematic

    # UI-only (preserves line breaks exactly)
    print_ui(
        "\n"
        "Credits\n"
        "\n"
        "A video game by Keith Mathewson\n"
        "\n"
        "Music by:\n"
        "Natacha Polké\n"
        "Richy Mitch & The Coal Miners\n"
        "\n"
        "SFX by:\n"
        "Eleven Labs\n"
        "\n"
    )

    print_icon(Fore.WHITE)

    pause_continue()

    # Do NOT exit alt screen here — main_menu now owns the alt screen lifecycle.
    main_menu()

def new_game():
    global game_state
    game_state = "running"
    global level
    level = "one"
    global active_gameplay_track
    active_gameplay_track = "level1"
    global pause_enabled
    pause_enabled = True
        
    random_character()

    enter_alt_screen()   # Isolates gameplay from terminal history
    wipe_visible()       # Visible blank screen

    reset_story_log()
    title_banner(store_in_log=True)
    intro()
    entry_point()
    level_progression()

if __name__ == "__main__":
    try:
        main_menu()
    except KeyboardInterrupt:
        # If something (terminal weirdness) triggers an interrupt, exit cleanly
        clear_screen()
        print_pause("\n(Interrupt received — exiting cleanly)\n")
    finally:
        # make sure audio and terminal state are sane on exit
        try:
            bg_stop()
            SFX_CH.stop()
            PAUSE_CH.stop()
        except Exception:
            pass

        # Leave alternate screen buffer when the program truly exits.
        try:
            exit_alt_screen()  # <-- NEW
        except Exception:
            pass

        try:
            sys.stdout.write("\x1b[0m\x1b[?25h")
            sys.stdout.flush()
        except Exception:
            pass
