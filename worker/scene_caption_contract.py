"""Lightweight deterministic vetoes for strong contradictions in VLM scene captions."""
import re
from wardrobe_contract import wants_unclothed, clothing_alignment
from scene_action_contract import resolve_scene_action

_EXTRA_PERSON=re.compile(
    r"\b(?:another (?:person|woman|man|adult|figure|stands|is)|"
    r"two (?:people|persons|women|men|adults)|"
    r"second (?:person|woman|man|adult|figure))\b",re.I)

_EXPLICIT_SOLO=re.compile(
    r"\b(?:(?:only|just|exactly)\s+(?:one|a|single)|"
    r"(?:a|one)\s+(?:single|lone))\s+"
    r"(?:adult\s+)?(?:person|people|man|woman|adult|figure|character)\b",
    re.I)

def _negated_count_mention(text, start):
    """Ignore a local negation immediately preceding a count phrase.

    This is only a caption heuristic, not independent evidence of scene count.
    Other positive mentions in the same caption still count.
    """
    prefix = text[max(0, start - 32):start]
    return bool(re.search(r"\b(?:no|not|without|never)\s+(?:even\s+)?(?:a\s+)?$", prefix, re.I))


def _asserts_extra_person(caption):
    text = str(caption or "")
    return any(not _negated_count_mention(text, match.start())
               for match in _EXTRA_PERSON.finditer(text))


def caption_asserts_single_person(caption):
    """Only unnegated SOLO claims without explicit extra people count."""
    text = str(caption or "")
    if _asserts_extra_person(text):
        return False
    return any(not _negated_count_mention(text, match.start())
               for match in _EXPLICIT_SOLO.finditer(text))

def insufficient_scene_caption(caption):
    """A bare count such as 'Two.' is not evidence of an accurate scene."""
    words=re.findall(r"[a-zA-Z]+",str(caption or ""))
    return len(words)<8

def scene_action_conflicts(characters,caption,narrator_prompt):
    """Veto clear contradictions between a requested wall brace and actual pose.

    Only assert a failure for an explicit observation, not VLM silence.
    """
    people=characters if isinstance(characters,list) else []
    if len(people)!=1 or not caption:
        return []
    intended=str(narrator_prompt or "").lower()
    pose=str(people[0].get("pose","")).lower()
    wants_brace=resolve_scene_action({
        "composition":"neural_story","characters":people,
        "prompt":narrator_prompt
    })["required"]
    if not wants_brace:
        return []
    desc=str(caption).lower()
    if re.search(r"(?<![a-z])(?:lying|laying|reclining|crawling|sitting|kneeling|crouching|squatting)(?![a-z])",desc):
        return ["CG physical pose contradicts intended standing wall contact"]
    if re.search(r"(?<![a-z])(?:hand|hands|elbow|elbows)(?![a-z]).{0,25}"
                 r"(?<![a-z])(?:ground|paving|pavement|street)(?![a-z])",desc):
        return ["CG hands are on the ground instead of on the required wall"]
    return []


def scene_caption_conflicts(characters,caption):
    people=characters if isinstance(characters,list) else []
    desc=str(caption or "")
    reasons=[]
    if insufficient_scene_caption(desc):
        reasons.append("VLM did not describe CG contents well enough to verify the scene")
    if len(people)==1 and _asserts_extra_person(desc):
        reasons.append("Neural CG contains an additional principal figure according to VLM")
    if len(people)==1 and wants_unclothed(people[0].get("outfit","")):
        # A definite visible clothing contradiction is evidence; silence,
        # ambiguous framing or uncertain captions are not.
        if clothing_alignment(desc)=="failed":
            reasons.append("Neural CG wardrobe contradicts requested unclothed state")
    return reasons
