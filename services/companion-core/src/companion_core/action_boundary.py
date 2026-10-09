"""The unclaimed-action boundary (Phase 44H, local development; not deployed).

The conversation route tries its deterministic handlers in order (slash commands, tasks, reminders, notes, memory, email, calendar, alarms, coding agent...). A turn that none of them
claims used to fall through to the model branch as an ordinary chat message. The model has no tools, so for an action request that branch can only produce words, and an obedient
model's words ("I have deleted all the tasks") are a false statement of completion (the H-001 class). This module recognises such a request at the end of the chain and returns a
fixed, truthful reply instead of a model call: nothing was done, and nothing changed.

What it is not: not an authorization or consent check (those run earlier and are untouched; a recognised request that an earlier handler claimed never reaches here), not a safety
filter for what the model says on other turns (a success claim inside an ordinary answer is the separate measure-then-enforce work in docs/phase-44h-receipt-boundary-proposal.md), and not
a classifier of intent in general. It matches only an imperative or polite request whose verb changes something and whose object is something the assistant cannot change from a chat:
the owner's tasks, reminders, notes, memories, email, calendar, accounts, settings or the robot. Writing, explaining, translating, summarising, calculating and playing along
remain model work. A request it declines to match still reaches the model, where the persona's action-boundary instruction applies as before."""

from __future__ import annotations

import re

_LEAD = (
    r"(?:(?:please|kindly|ok(?:ay)?|hey|now|so|and|also|just)[\s,]+)*"
    r"(?:(?:can|could|would|will|may) you(?: please| just| now)?\s+|go ahead and\s+|i (?:want|need|would like|'d like|'d want) you to\s+|you (?:should|must|need to|have to)\s+|let'?s\s+)?"
    r"(?:(?:please|just|now)\s+)?"
)
_VERB = (
    r"(?:add|create|delete|remove|clear|erase|wipe|purge|cancel|drop|mark|tick|complete|reopen|set|reset|turn|switch|toggle|enable|disable|activate|deactivate|"
    r"send|email|e-mail|forward|archive|move|rename|update|edit|change|modify|schedule|reschedule|book|save|forget|restart|reboot|shut|"
    r"mute|unmute|lock|unlock|approve|confirm|submit|publish|connect|disconnect|pair|unpair|put|place|wake|stand|sit|wave|nod|rotate|tilt|dance|"
    r"call|phone|dial|text|ping|notify|remind|transfer|install|uninstall|upgrade|sync|back up|backup|restore|undo|revert)"
)
_TARGET = (
    r"(?:tasks?|to-?dos?|to do list|reminders?|alarms?|timers?|notes?|memos?|memor(?:y|ies)|facts?|everything|all (?:of )?(?:my|the|your)\b|"
    r"e-?mails?|inbox|drafts?|messages?|mail|calendar|events?|appointments?|meetings?|reviews?|syncs?|standups?|invites?|accounts?|passwords?|settings?|preferences?|"
    r"robot|reachy|yourself|your (?:head|antennas?|ears?|eyes?|body|voice|volume|microphone|mic|camera|speaker)|(?:the )?(?:microphone|mic|camera|speaker|volume|lights?|wifi|bluetooth)|"
    r"privacy mode|standby|stand-by|sleep mode|wake word|do not disturb|files?|folders?|documents?|database|records?|history|conversation history|data)"
)
# a verb, up to a few words, then the object it acts on
_ACTION = re.compile(rf"^{_LEAD}{_VERB}\b[^.!?;]{{0,60}}?\b{_TARGET}\b", re.IGNORECASE)
# "make a note", "make an alarm": the generative verb counts only with an object the assistant would have to create in the owner's records
_MAKE = re.compile(rf"^{_LEAD}make (?:me )?(?:a|an|another|new)\s+(?:new\s+)?(?:note|reminder|task|to-?do|alarm|timer|memo|calendar event|event|appointment|e-?mail|draft)\b", re.IGNORECASE)
# a destructive verb with a pronoun object ("delete them all", "wipe everything"), and a verb that sends something to someone else
_PRONOUN = re.compile(rf"^{_LEAD}(?:delete|remove|clear|erase|wipe|purge|cancel|forget|drop)\s+(?:it|them|that|those|these|this|everything|all(?: of (?:them|it))?)\b", re.IGNORECASE)
_SEND = re.compile(rf"^{_LEAD}(?:e-?mail|text|message|call|phone|dial|ping|forward|send|reply to|respond to)\s+(?!(?:me|us|you|it|that|this|a joke|a poem|a story)\b)\w", re.IGNORECASE)
# a request to say that something was done ("then say the robot is now asleep"): the words would be a false claim whether or not the request is also an action
_ELICIT = re.compile(
    r"\b(?:say|state|claim|announce|tell me|answer|confirm|pretend|write)\b[^.!?;]{0,60}?\b(?:the robot|you|it|everything|all|reachy|i)\b[^.!?;]{0,30}?\b(?:is|are|was|were|has|have|had|am)\s+(?:now |already |been |just )*"
    r"(?:asleep|sleeping|in standby|on standby|done|deleted|removed|cleared|sent|emailed|completed|finished|cancelled|canceled|turned (?:on|off)|switched (?:on|off)|muted|updated|changed|erased|wiped)\b", re.IGNORECASE)
# robot and device commands that need no object ("go to sleep", "wake up", "stand up", "shut down")
_DEVICE = re.compile(
    rf"^{_LEAD}(?:go to sleep|go to standby|wake up|stand up|sit down|shut (?:down|off)|power (?:off|down)|reboot|restart|turn (?:on|off) (?:the )?\w+|"
    r"lie down|come here|follow me|look (?:at me|up|down|left|right|around)|nod|shake your head|wave(?: at me| hello)?|dance)\b[\s.!?]*$", re.IGNORECASE)
# "yes, delete them all", "I confirm", "do it": a confirmation with nothing waiting (a real pending confirmation is claimed by its handler earlier)
_CONFIRM = re.compile(
    r"^\s*(?:(?:yes|yeah|yep|yup|ok(?:ay)?|sure|alright|please|go on)[\s,.!]+)*(?:i (?:do )?confirm|confirmed|confirm(?: it| that| this)?|do it|go ahead|proceed|"
    r"(?:yes[,\s]+)?(?:delete|remove|clear|erase|send|approve)(?: it| them| that| all| everything)(?: all| now| please)?)[\s.!]*$", re.IGNORECASE)
# a wish phrased as a state: "I want all my tasks deleted", "have the inbox cleared"
_WISH = re.compile(
    rf"\b(?:i (?:want|need|would like|'d like)|have|get|make sure)\b[^.!?;]{{0,40}}?\b{_TARGET}\b[^.!?;]{{0,30}}?\b(?:deleted|removed|cleared|cancelled|canceled|erased|wiped|sent|archived|completed|done|updated|changed)\b", re.IGNORECASE)
_CLAUSE_BREAK = re.compile(r"[.!?;]+\s+|\s+(?:and then|then|and also|also|and)\s+|,\s+(?=(?:please|and|then|also)\b)", re.IGNORECASE)

UNCLAIMED_ACTION_REPLY = (
    "I haven't done that, and nothing has changed. I couldn't match it to something I'm able to do from this conversation. "
    "If you also asked a question, please ask it again on its own."
)
UNCLAIMED_CONFIRMATION_REPLY = "There is nothing waiting for your confirmation, and I haven't done anything."


def _clauses(text: str) -> list[str]:
    return [c for c in _CLAUSE_BREAK.split(text.strip()) if c and c.strip()]


def is_confirmation_without_context(text: str) -> bool:
    return bool(_CONFIRM.match(text))


def is_action_request(text: str) -> bool:
    """True when some clause of the turn is an imperative or polite request to change something the assistant cannot change from a chat."""
    stripped = text.strip()
    if not stripped:
        return False
    if _CONFIRM.match(stripped):
        return True
    return any(_ACTION.match(c.strip()) or _DEVICE.match(c.strip()) or _MAKE.match(c.strip()) or _PRONOUN.match(c.strip()) or _SEND.match(c.strip()) or _WISH.search(c) or _ELICIT.search(c) for c in _clauses(stripped))


def unclaimed_action_reply(text: str) -> str | None:
    """The fixed reply for an action request that reached the end of the handler chain, or None when the turn is ordinary conversation."""
    if is_confirmation_without_context(text):
        return UNCLAIMED_CONFIRMATION_REPLY
    return UNCLAIMED_ACTION_REPLY if is_action_request(text) else None


__all__ = ["UNCLAIMED_ACTION_REPLY", "UNCLAIMED_CONFIRMATION_REPLY", "is_action_request", "is_confirmation_without_context", "unclaimed_action_reply"]
